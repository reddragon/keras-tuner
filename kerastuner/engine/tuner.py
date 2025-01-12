# Copyright 2019 The Keras Tuner Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"Meta classs for hypertuner"
from __future__ import absolute_import, division, print_function

import gc
import hashlib
import json
import os
import socket
import sys
import time
from abc import abstractmethod
from collections import defaultdict
from pathlib import Path
import traceback

# used to check if supplied model_fn is a valid model
from tensorflow.keras.models import Model  # pylint: disable=import-error
from kerastuner.abstractions.tensorflow import TENSORFLOW_UTILS as tf_utils
from kerastuner.abstractions.display import highlight, display_table, section
from kerastuner.abstractions.display import display_setting, display_settings
from kerastuner.abstractions.display import info, warning, fatal, set_log
from kerastuner.abstractions.display import progress_bar, subsection
from kerastuner.abstractions.display import colorize, colorize_default
from kerastuner.abstractions.tensorflow import TENSORFLOW_UTILS as tf_utils
from kerastuner.tools.summary import results_summary as _results_summary
from kerastuner import config
from kerastuner.states import TunerState, InstanceState
from .cloudservice import CloudService
from .instance import Instance
from kerastuner.collections import InstanceStatesCollection
from kerastuner.abstractions.io import reload_model, exists
from kerastuner.abstractions.io import get_weights_filename
from sklearn.model_selection import train_test_split


class Tuner(object):
    """Abstract hypertuner class."""

    def __init__(self, model_fn, objective, name, distributions, **kwargs):
        """ Tuner abstract class

        Args:
            model_fn (function): Function that return a Keras model
            name (str): name of the tuner
            objective (str): Which objective the tuner optimize for
            distributions (Distributions): distributions object

        Notes:
            All meta data and varialbles are stored into self.state
            defined in ../states/tunerstate.py
        """

        # hypertuner state init
        self.state = TunerState(name, objective, **kwargs)
        self.stats = self.state.stats  # shorthand access
        self.cloudservice = CloudService()

        # check model function
        if not model_fn:
            fatal("Model function can't be empty")
        try:
            mdl = model_fn()
        except:
            traceback.print_exc()
            fatal("Invalid model function")

        if not isinstance(mdl, Model):
            t = "tensorflow.keras.models.Model"
            fatal("Invalid model function: Doesn't return a %s object" % t)

        # function is valid - recording it
        self.model_fn = model_fn

        # Initializing distributions
        hparams = config._DISTRIBUTIONS.get_hyperparameters_config()
        if len(hparams) == 0:
            warning("No hyperparameters used in model function. Are you sure?")

        # set global distribution object to the one requested by tuner
        # !MUST be after _eval_model_fn()
        config._DISTRIBUTIONS = distributions(hparams)

        # instances management
        self.max_fail_streak = 5  # how many failure before giving up
        self.instance_states = InstanceStatesCollection()

        # previous models
        print("Loading from %s" % self.state.host.results_dir)
        count = self.instance_states.load_from_dir(self.state.host.results_dir,
                                                   self.state.project,
                                                   self.state.architecture)
        self.stats.instance_states_previously_trained = count
        info("Tuner initialized")

    def summary(self, extended=False):
        """Print tuner summary

        Args:
            extended (bool, optional): Display extended summary.
            Defaults to False.
        """
        section('Tuner summary')
        self.state.summary(extended=extended)
        config._DISTRIBUTIONS.config_summary()

    def enable_cloud(self, api_key, url=None):
        """Enable cloud service reporting

            Args:
                api_key (str): The backend API access token.
                url (str, optional): The backend base URL.

            Note:
                this is called by the user
        """
        self.cloudservice.enable(api_key, url)

    def search(self, x, y=None, **kwargs):
        kwargs["verbose"] = 0

        validation_data = None

        if "validation_split" in kwargs and "validation_data" in kwargs:
            raise ValueError(
                "Specify validation_data= or validation_split=, but not both.")

        if "validation_split" in kwargs and "validation_data" not in kwargs:
            val_split = kwargs["validation_split"]
            x, x_validation = train_test_split(x, test_size=val_split)
            if y is not None:
                y, y_validation = train_test_split(y, test_size=val_split)
            else:
                y, y_validation = None, None
            validation_data = (x_validation, y_validation)
            del kwargs["validation_split"]
        elif "validation_data" in kwargs:
            validation_data = kwargs["validation_data"]
            del kwargs["validation_data"]

        self.tune(x, y, validation_data=validation_data, **kwargs)
        if self.cloudservice.is_enable:
            self.cloudservice.complete()

    def new_instance(self):
        "Return a never seen before model instance"
        fail_streak = 0
        collision_streak = 0
        over_sized_streak = 0

        while 1:
            # clean-up TF graph from previously stored (defunct) graph
            tf_utils.clear_tf_session()
            self.stats.generated_instances += 1
            fail_streak += 1
            try:
                model = self.model_fn()
            except:
                if self.state.debug:
                    traceback.print_exc()

                self.stats.invalid_instances += 1
                warning("invalid model %s/%s" %
                        (self.stats.invalid_instances, self.max_fail_streak))

                if self.stats.invalid_instances >= self.max_fail_streak:
                    warning("too many consecutive failed models - stopping")
                    return None
                continue

            # stop if the model_fn() return nothing
            if not model:
                warning("No model returned from model function - stopping.")
                return None

            # computing instance unique idx
            idx = self.__compute_model_id(model)
            if self.instance_states.exist(idx):
                collision_streak += 1
                self.stats.collisions += 1
                warning("Collision for %s -- skipping" % (idx))
                if collision_streak >= self.max_fail_streak:
                    return None
                continue

            # check size
            nump = tf_utils.compute_model_size(model)
            if nump > self.state.max_model_parameters:
                over_sized_streak += 1
                self.stats.over_sized_models += 1
                warning("Oversized model: %s parameters-- skipping" % (nump))
                if over_sized_streak >= self.max_fail_streak:
                    warning("too many consecutive failed model - stopping")
                    return None
                continue

            # creating instance
            hparams = config._DISTRIBUTIONS.get_hyperparameters()
            instance = Instance(idx, model, hparams, self.state,
                                self.cloudservice)
            break

        # recording instance
        self.instance_states.add(idx, instance.state)
        return instance

    def reload_instance(self, idx, execution="last", metrics=[]):
        tf_utils.clear_tf_session()

        instance_state = self.instance_states.get(idx)
        if not instance_state:
            raise ValueError("Attempted to reload unknown instance '%s'." %
                             idx)

        # Find the specified execution.
        executions = instance_state.execution_states_collection
        execution_state = None
        if execution == "last":
            execution_state = executions.get_last()
        elif execution == "best":
            execution_state = executions.sort_by_metric(
                self.state.objective).to_list()[0]
        elif execution:
            execution_state = executions.get(idx)

        weights_filename = get_weights_filename(self.state, instance_state,
                                                execution_state)

        model = InstanceState.model_from_configs(
            instance_state.model_config,
            instance_state.loss_config,
            instance_state.optimizer_config,
            instance_state.metrics_config,
            weights_filename=weights_filename)

        instance = Instance(idx=instance_state.idx,
                            model=model,
                            hparams=instance_state.hyper_parameters,
                            tuner_state=self.state,
                            cloudservice=self.cloudservice,
                            instance_state=instance_state)
        return instance

    def get_best_models(self, num_models=1, compile=False):
        """Returns the best models, as determined by the tuner's objective.

        Args:
            num_models (int, optional): Number of best models to return.
                Models will be returned in sorted order. Defaults to 1.
            compile (bool, optional): If True, infer the loss and optimizer,
                and compile the returned models. Defaults to False.

        Returns:
            tuple: Tuple containing a list of InstanceStates, a list of
                ExecutionStates, and a list of Models, where the Nth Instance
                and Nth Execution correspond to the Nth Model.
        """
        sorted_instance_states = self.instance_states.sort_by_objective()
        if len(sorted_instance_states) > num_models:
            sorted_instance_states = sorted_instance_states[:num_models]

        execution_states = []
        for instance_state in sorted_instance_states:
            sorted_execution_list = (
                instance_state.execution_states_collection.sort_by_metric(
                    instance_state.objective))
            best_execution_state = sorted_execution_list[0]
            execution_states.append(best_execution_state)

        models = []
        for instance_state, execution_state in zip(sorted_instance_states,
                                                   execution_states):

            model = reload_model(self.state,
                                 instance_state,
                                 execution_state,
                                 compile=True)
            models.append(model)

        return sorted_instance_states, execution_states, models

    def save_best_model(self, export_type="keras"):
        """Shortcut for save_best_models for the case of only keeping the best
        model."""
        return self.save_best_models(export_type=export_type, num_models=1)

    def save_best_models(self, export_type="keras", num_models=1):
        """ Exports the best model based on the specified metric, to the
            results directory.

            Args:
                output_type (str, optional): Defaults to "keras". What format
                    of model to export:

                    # Tensorflow 1.x/2.x
                    "keras" - Save as separate config (JSON) and weights (HDF5)
                        files.
                    "keras_bundle" - Saved in Keras's native format (HDF5), via
                        save_model()

                    # Currently only supported in Tensorflow 1.x
                    "tf" - Saved in tensorflow's SavedModel format. See:
                        https://www.tensorflow.org/alpha/guide/saved_model
                    "tf_frozen" - A SavedModel, where the weights are stored
                        in the model file itself, rather than a variables
                        directory. See:
                        https://www.tensorflow.org/guide/extend/model_files
                    "tf_optimized" - A frozen SavedModel, which has
                        additionally been transformed via tensorflow's graph
                        transform library to remove training-specific nodes
                        and operations.  See:
                        https://github.com/tensorflow/tensorflow/tree/master/tensorflow/tools/graph_transforms
                    "tf_lite" - A TF Lite model.
        """

        instance_states, execution_states, models = self.get_best_models(
            num_models=num_models, compile=False)

        zipped = zip(models, instance_states, execution_states)
        for idx, (model, instance_state, execution_state) in enumerate(zipped):
            export_prefix = "%s-%s-%s-%s" % (
                self.state.project, self.state.architecture,
                instance_state.idx, execution_state.idx)

            export_path = os.path.join(self.state.host.export_dir,
                                       export_prefix)

            tmp_path = os.path.join(self.state.host.tmp_dir, export_prefix)
            info("Exporting top model (%d/%d) - %s" %
                 (idx + 1, len(models), export_path))
            tf_utils.save_model(model,
                                export_path,
                                tmp_path=tmp_path,
                                export_type=export_type)

    def __compute_model_id(self, model):
        "compute model hash"
        s = str(model.get_config())
        # Optimizer and loss are not currently part of the model config,
        # but could conceivably be part of the model_fn/tuning process.
        if model.optimizer:
            s += "optimizer:" + str(model.optimizer.get_config())
        s += "loss:" + str(model.loss)
        return hashlib.sha256(s.encode('utf-8')).hexdigest()[:32]

    def results_summary(self, num_models=10, sort_metric=None):
        """Display tuning results summary.

        Args:
            num_models (int, optional): Number of model to display.
            Defaults to 10.
            sort_metric (str, optional): Sorting metric, when not specified
            sort models by objective value. Defaults to None.
        """
        if self.state.dry_run:
            info("Dry-Run - no results to report.")
            return

        # FIXME API documentation
        _results_summary(input_dir=self.state.host.results_dir,
                         project=self.state.project,
                         architecture=self.state.architecture,
                         num_models=num_models,
                         sort_metric=sort_metric)

    @abstractmethod
    def tune(self, x, y, **kwargs):
        "method called by the hypertuner to train an instance"

    @abstractmethod
    def retrain(self, idx, x, y, execution=None, metrics=[], **kwargs):
        "method called by the hypertuner to resume training an instance"
        instance = self.reload_instance(idx,
                                        execution=execution,
                                        metrics=metrics)
        instance.fit(x, y, self.state.max_epochs, **kwargs)

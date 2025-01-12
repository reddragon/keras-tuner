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

from __future__ import absolute_import

import pytest
from tensorflow.keras.layers import Input, Dense  # nopep8 pylint: disable=import-error
from tensorflow.keras.models import Model  # pylint: disable=import-error

from .common import is_serializable

from kerastuner.abstractions.tensorflow import TENSORFLOW_UTILS as tf_utils
from kerastuner.engine.instance import Instance
from kerastuner.states.instancestate import InstanceState
from kerastuner.collections.metricscollection import MetricsCollection


@pytest.fixture(scope='class')
def basic_model():
    i = Input(shape=(1,), name="input")
    o = Dense(4, name="output")(i)
    model = Model(inputs=i, outputs=o)
    model.compile(optimizer="adam", loss='mse', metrics=['accuracy'])
    return model


@pytest.fixture(scope='class')
def hparams():
    hparams = {}
    hparams['g1:p1'] = {'name': 'p1', 'value': 3713, 'group': 'g1'}
    return hparams


def test_is_serializable(hparams, basic_model):
    state = InstanceState('3713', basic_model, hparams)
    is_serializable(state)


def test_from_config(hparams, basic_model):
    state = InstanceState('3713', basic_model, hparams)
    state.agg_metrics = MetricsCollection()
    state.agg_metrics.add('accuracy')
    state.agg_metrics.update('acc', 11)
    state.set_objective("accuracy")
    config = state.to_config()

    state2 = InstanceState.from_config(config)
    assert state2.objective == state.objective
    for k in config.keys():
        assert config[k] == config[k]


def test_summary(hparams, basic_model, capsys):
    idx = '3713'
    state = InstanceState(idx, basic_model, hparams)
    state.summary()
    captured = capsys.readouterr()
    to_test = [
        'model size: %s' % tf_utils.compute_model_size(basic_model),
        'idx: %s' % idx,
    ]
    for s in to_test:
        assert s in captured.out


def test_extended_summary_working(hparams, basic_model, capsys):
    idx = '3713'
    state = InstanceState(idx, basic_model, hparams)
    summary_out = capsys.readouterr()
    state.summary(extended=True)
    extended_summary_out = capsys.readouterr()
    assert summary_out.out.count(":") < extended_summary_out.out.count(":")

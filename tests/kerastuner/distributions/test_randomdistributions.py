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

from collections import defaultdict

from kerastuner.distributions import RandomDistributions
from .common import record_hyperparameters_test, json_serialize_test
from .common import fixed_correctness_test, bool_correctness_test
from .common import choice_correctness_test, range_type_correctness_test
from .common import linear_correctness_test, logarithmic_correctness_test

# number of elements to draw - sample_size < 1000 cause flakiness
SAMPLE_SIZE = 10000
rand = RandomDistributions({})


# Hyperparameters
def test_record_hyperparameters():
    record_hyperparameters_test(RandomDistributions({}))


# Fixed
def test_fixed_correctness():
    fixed_correctness_test(RandomDistributions({}))


def test_fixed_serialize():
    json_serialize_test(rand.Fixed('rand', 1))


# Boolean
def test_bool_correctness():
    bool_correctness_test(RandomDistributions({}))


def test_bool_serialize():
    json_serialize_test(rand.Boolean('bool'))


def test_bool_randomness():
    distributions = RandomDistributions({})
    res = defaultdict(int)
    for _ in range(SAMPLE_SIZE):
        x = distributions.Boolean("test")
        res[x] += 1
    prob = round(res[True] / float(SAMPLE_SIZE), 1)
    assert prob == 0.5


# Choice
def choice_range_correctness():
    choice_correctness_test(RandomDistributions({}))


def test_choice_serialize():
    tests = [
        rand.Choice('choice', [1, 2, 3]),
        rand.Choice('choice', [1.0, 2.0, 3.0]),
        rand.Choice('choice', ['a', 'b', 'c']),
    ]
    for test in tests:
        json_serialize_test(test)


def test_choice_randomness():
    distributions = RandomDistributions({})
    res = defaultdict(int)
    for _ in range(SAMPLE_SIZE):
        x = distributions.Choice("test", ['a', 'b', 'c'])
        res[x] += 1
    prob = round(res['a'] / float(SAMPLE_SIZE), 1)
    assert prob == 0.3


# Range
def range_range_correctness():
    range_type_correctness_test(RandomDistributions({}))


def test_range_randomness():
    distributions = RandomDistributions({})
    res = defaultdict(int)
    for _ in range(SAMPLE_SIZE):
        x = distributions.Range("test", 1, 100)
        res[x] += 1
    prob = round(res[42] / float(SAMPLE_SIZE), 2)
    assert prob == 0.01


# Linear
def test_linear_correctness():
    linear_correctness_test(RandomDistributions({}))


def test_linear_int_randomness():
    distributions = RandomDistributions({})
    res = defaultdict(int)
    num_buckets = 100
    for _ in range(SAMPLE_SIZE):
        x = distributions.Linear("test", 1, 100, num_buckets)
        res[x] += 1
    prob = round(res[42] / float(SAMPLE_SIZE), 1)
    assert prob == round(1 / float(num_buckets), 1)


def test_linear_float_randomness():
    distributions = RandomDistributions({})
    res = defaultdict(int)
    num_buckets = 100
    for _ in range(SAMPLE_SIZE):
        x = distributions.Linear("test", 1.0, 100.0, num_buckets)
        res[x] += 1
    prob = round(res[42] / float(SAMPLE_SIZE), 1)
    assert prob == round(1 / float(num_buckets), 1)


# Logarithmic
def test_logarithmic_correctness():
    logarithmic_correctness_test(RandomDistributions({}))

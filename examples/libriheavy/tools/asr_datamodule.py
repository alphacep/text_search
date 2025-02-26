# Copyright      2021  Piotr Żelasko
# Copyright      2022  Xiaomi Corporation     (Author: Mingshuang Luo)
# Copyright      2023  Xiaomi Corporation     (Author: Zengwei Yao)
# Copyright      2023  Xiaomi Corporation     (Author: Wei Kang)
#
# See ../../../../LICENSE for clarification regarding multiple authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import argparse
import logging
from typing import Dict, List, Union

import torch
from lhotse import CutSet, Fbank, FbankConfig
from lhotse.cut import Cut
from lhotse.dataset import (
    K2SpeechRecognitionDataset,
    SimpleCutSampler,
)
from lhotse.dataset.input_strategies import (
    BatchIO,
    OnTheFlyFeatures,
)
from torch.utils.data import DataLoader

from textsearch.utils import str2bool


class SpeechRecognitionDataset(K2SpeechRecognitionDataset):
    def __init__(
        self,
        return_cuts: bool = False,
        input_strategy: BatchIO = OnTheFlyFeatures(Fbank()),
    ):
        super().__init__(return_cuts=return_cuts, input_strategy=input_strategy)

    def __getitem__(
        self, cuts: CutSet
    ) -> Dict[str, Union[torch.Tensor, List[Cut]]]:
        """
        Return a new batch, with the batch size automatically determined using the constraints
        of max_frames and max_cuts.
        """
        self.hdf5_fix.update()

        # Note: don't sort cuts here
        # Sort the cuts by duration so that the first one determines the batch time dimensions.
        # cuts = cuts.sort_by_duration(ascending=False)

        # Get a tensor with batched feature matrices, shape (B, T, F)
        # Collation performs auto-padding, if necessary.
        input_tpl = self.input_strategy(cuts)
        if len(input_tpl) == 3:
            # An input strategy with fault tolerant audio reading mode.
            # "cuts" may be a subset of the original "cuts" variable,
            # that only has cuts for which we succesfully read the audio.
            inputs, _, cuts = input_tpl
        else:
            inputs, _ = input_tpl

        # Get a dict of tensors that encode the positional information about supervisions
        # in the batch of feature matrices. The tensors are named "sequence_idx",
        # "start_frame/sample" and "num_frames/samples".
        supervision_intervals = self.input_strategy.supervision_intervals(cuts)

        batch = {"inputs": inputs, "supervisions": supervision_intervals}
        if self.return_cuts:
            batch["supervisions"]["cut"] = [cut for cut in cuts]

        return batch


class AsrDataModule:
    """
    DataModule for k2 ASR experiments.
    """

    def __init__(self, args: argparse.Namespace):
        self.args = args

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser):
        group = parser.add_argument_group(
            title="ASR data related options",
            description="These options are used for the preparation of "
            "PyTorch DataLoaders from Lhotse CutSet's -- they control the "
            "effective batch sizes, sampling strategies, applied data "
            "augmentations, etc.",
        )
        group.add_argument(
            "--max-duration",
            type=int,
            default=600.0,
            help="Maximum pooled recordings duration (seconds) in a "
            "single batch. You can reduce it if it causes CUDA OOM.",
        )
        group.add_argument(
            "--return-cuts",
            type=str2bool,
            default=True,
            help="When enabled, each batch will have the "
            "field: batch['supervisions']['cut'] with the cuts that "
            "were used to construct it.",
        )
        group.add_argument(
            "--num-mel-bins",
            type=int,
            default=80,
            help="The number of melbank bins for fbank",
        )
        group.add_argument(
            "--num-workers",
            type=int,
            default=8,
            help="The number of training dataloader workers that "
            "collect the batches.",
        )

    def dataloaders(self, cuts: CutSet) -> DataLoader:
        logging.debug("About to create test dataset")
        dataset = SpeechRecognitionDataset(
            input_strategy=OnTheFlyFeatures(
                Fbank(FbankConfig(num_mel_bins=self.args.num_mel_bins))
            ),
            return_cuts=self.args.return_cuts,
        )

        sampler = SimpleCutSampler(
            cuts,
            max_duration=self.args.max_duration,
            shuffle=False,
            drop_last=False,
        )

        logging.debug("About to create test dataloader")
        dl = DataLoader(
            dataset,
            batch_size=None,
            sampler=sampler,
            num_workers=self.args.num_workers,
            persistent_workers=False,
        )
        return dl

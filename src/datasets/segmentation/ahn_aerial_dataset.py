import os
import os.path as osp
import sys

import torch
from torch.utils.data import RandomSampler
from torch_geometric.data import InMemoryDataset

ROOT = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "..")
sys.path.append(ROOT)

from src.datasets.base_patch_dataset import Grid2DPatchDataset, BaseMultiCloudPatchDataset, FailSafeIterableDataset, UniqueRandomSampler, UniqueSequentialSampler
from src.datasets.base_dataset import BaseDataset
from src.metrics.ahn_tracker import AHNTracker
from utils.custom_datasets.ahn_pointcloud import AHNPointCloud

class AHNTilesDataset(InMemoryDataset):

    adriaan_tiles_train = [
            '37EN2_11.LAZ',
            '37EN2_16.LAZ',
            '43FZ2_20.LAZ',
    ]
    adriaan_tiles_test = [
            '37FZ2_21.LAZ',

    ]

    small_tile = [
        '37EN2_11_section.laz'
    ]

    tiny_tile = [
        '37EN2_11_section_tiny.laz'
    ]


    def __init__(self, root, split, transform=None, pre_transform=None, pre_filter=None):

        self.split = split

        super().__init__(root, transform, pre_transform, pre_filter)

        self.data, self.slices = torch.load(self.processed_paths[0])

    @property
    def raw_file_names(self):
        if self.split == 'eval':
            return self.adriaan_tiles_test
        return self.adriaan_tiles_train if self.split == 'train' else self.adriaan_tiles_test
        # return self.small_tile
        
    @property
    def processed_file_names(self):
        return ['{}_data.pt'.format('_'.join(self.raw_file_names))]

    def download(self):
        raise NotImplementedError

    def process(self):

        data_list = []

        for raw_path in self.raw_paths:
            pcd = AHNPointCloud.from_cloud(raw_path)

            data_list.append(pcd.to_torch_data())

        torch.save(self.collate(data_list), self.processed_paths[0])

class AHNPatchDataset(Grid2DPatchDataset):

    def __init__(self, data, patch_diam=10, context_dist=0.3, *args, **kwargs):
        super().__init__(data, patch_diam, patch_diam, context_dist, *args, **kwargs)

        self.num_classes = 5

    @classmethod
    def from_tiles_dataset(cls, dataset: AHNTilesDataset, **kwargs):
        assert len(dataset) == 1
        return cls(dataset[0], **kwargs)

class AHNMultiCloudPatchDataset(BaseMultiCloudPatchDataset):

    def __init__(self, backingDataset, patch_opt):
        super().__init__([
            AHNPatchDataset(data, **patch_opt) for data in backingDataset
        ])

        self.num_classes = 5


class AHNAerialDataset(BaseDataset):

    def __init__(self, dataset_opt, training_opt, eval_mode=False):
        super().__init__(dataset_opt, training_opt)
        self._data_path = osp.join(ROOT, dataset_opt.dataroot, "AHNTilesDataset")

        if eval_mode:
            self._init_for_eval(dataset_opt, training_opt)
        else:

            train_patch_dataset = AHNMultiCloudPatchDataset(
                AHNTilesDataset(self._data_path, "train"),
                dataset_opt.patch_opt,
            )
            self.train_dataset = FailSafeIterableDataset(
                train_patch_dataset,
                UniqueRandomSampler(
                    train_patch_dataset,
                    replacement=True,
                    num_samples=100//training_opt.num_workers, #sample ~100 patches in total per epoch
                )
            )
            test_patch_dataset = AHNMultiCloudPatchDataset(
                AHNTilesDataset(self._data_path, "test"),
                dataset_opt.patch_opt,
            )
            self.test_dataset = FailSafeIterableDataset(
                test_patch_dataset,
                UniqueRandomSampler(
                    test_patch_dataset,
                    replacement=True,
                    num_samples=50//training_opt.num_workers,
                )
            )


            # self._create_dataloaders(
            #     self.train_dataset, 
            #     self.test_dataset, 
            #     validation=None,
            #     train_sampler=RandomSampler(
            #         self.train_dataset, 
            #         replacement=True,
            #         num_samples=100
            #     ),
            #     test_sampler=RandomSampler(
            #         self.test_dataset,
            #         replacement=True,
            #         num_samples=50
            #     )
            # )
            self._create_dataloaders(
                self.train_dataset,
                self.test_dataset,
                val_dataset=None,
            )

        self.pointcloud_scale = dataset_opt.scale

    def _init_for_eval(self, dataset_opt, training_opt):

        test_patch_dataset = AHNPatchDataset.from_tiles_dataset(
            AHNTilesDataset(self._data_path, "eval"),
            **dataset_opt.patch_opt,
            eval_mode=True,
        )
        self.test_dataset = FailSafeIterableDataset(
            test_patch_dataset,
            UniqueSequentialSampler(
                training_opt.num_workers,
                test_patch_dataset
            )
        )

        self._create_dataloaders(
            self.test_dataset,
            self.test_dataset,
            validation=None
        )

    @property
    def class_num_to_name(self):
        return AHNPointCloud.clasNumToName()

    @property
    def class_to_segments(self):
        return {
            k: [v] for k, v in AHNPointCloud.clasNameToNum().items()
        }

    @staticmethod
    def get_tracker(model, task: str, dataset, wandb_opt: bool, tensorboard_opt: bool):
        """Factory method for the tracker

        Arguments:
            task {str} -- task description
            dataset {[type]}
            wandb_log - Log using weight and biases
        Returns:
            [BaseTracker] -- tracker
        """
        return AHNTracker(dataset, wandb_log=wandb_opt.log, use_tensorboard=tensorboard_opt.log)



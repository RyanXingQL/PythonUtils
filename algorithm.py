import torch
import torch.nn as nn
from collections import OrderedDict
from torch.nn.parallel import DistributedDataParallel as DDP

from .system import print_n_log
from .metrics import return_crit_func
from .deep_learning import return_optimizer, return_loss_func, return_scheduler

class BaseAlg():
    def __init__(self):
        super().__init__()

    def create_model(self, model_cls, if_train, opts_dict):
        """
        model_cls + opts_dict
        -> self.model
            self.model.module_lst
        -> DDP(module)
        """
        opts_dict_ = dict(
            if_train=if_train,
            opts_dict=opts_dict,
            )
        self.model = model_cls(**opts_dict_)

        for mod_item in self.model.module_lst:
            self.model.module_lst[mod_item].cuda()
            self.model.module_lst[mod_item] = nn.SyncBatchNorm.convert_sync_batchnorm(self.model.module_lst[mod_item])  # convert all bn to syncbatchnorm
            self.model.module_lst[mod_item] = DDP(self.model.module_lst[mod_item], device_ids=[torch.cuda.current_device()])

    def print_net(self, log_fp):
        if hasattr(self.model, 'msg_lst'):
            for msg_key in self.model.msg_lst:
                print_n_log(self.model.msg_lst[msg_key], log_fp)

    def set_train_mode(self):
        """
        module.train()
        """
        for mod_key in self.model.module_lst:
            self.model.module_lst[mod_key].train()

    def set_eval_mode(self):
        """
        module.eval()
        """
        for mod_key in self.model.module_lst:
            self.model.module_lst[mod_key].eval()

    def create_loss_func(self, opts_dict, if_use_cuda=True):
        """
        opts_dict
        -> self.loss_lst
        -> (if_use_cuda) loss on cuda

        Args:
            opts_dict (example):
                xxx
        """
        self.loss_lst = dict()
        for loss_name in opts_dict:
            loss_func = return_loss_func(name=loss_name, opts=opts_dict[loss_name]['opts'])
            if if_use_cuda:
                loss_func = loss_func.cuda()
            self.loss_lst[loss_name] = dict(
                weight=opts_dict[loss_name]['weight'],
                fn=loss_func,
                )

    def create_optimizer(self, params_lst, opts_dict):
        """
        opts_dict
        -> self.optim_lst
        -> (if TTUR) lr for gen / 2, lr for dis * 2.

        Args:
            params_lst (example):
                gen: params_g
                dis: params_d
            opts_dict (example):
                xxx
        """
        opts_ttur = opts_dict.pop('TTUR')
        if_ttur = False
        if opts_ttur['if_ttur']:
            if_ttur = True
            lr = opts_ttur['lr']

        self.optim_lst = dict()
        for optim_item in opts_dict:
            if if_ttur:
                if optim_item == 'gen':
                    new_lr = lr / 2.
                elif optim_item == 'dis':
                    new_lr = lr * 2.
                opts_dict[optim_item]['opts']['lr'] = new_lr
            
            opts_dict_ = dict(
                name=opts_dict[optim_item]['type'],
                params=params_lst[optim_item],
                opts=opts_dict[optim_item]['opts'],
                )
            optim = return_optimizer(**opts_dict_)
            self.optim_lst[optim_item] = optim

    def create_scheduler(self, optim_lst, opts_dict):
        """
        opts_dict
        -> self.optim_lst

        Args:
            opts_dict (example):
                xxx
        """
        self.sched_lst = dict()
        for sched_item in opts_dict:
            opts_dict_ = dict(
                name=opts_dict[sched_item]['type'],
                optim=optim_lst[sched_item],
                opts=opts_dict[sched_item]['opts'],
                )
            sched = return_scheduler(**opts_dict_)
            self.sched_lst[sched_item] = sched

    def create_criterion(self, opts_dict):
        """
        opts_dict
        -> self.crit_lst

        Args:
            opts_dict (example):
                xxx
        """
        self.crit_lst = dict()
        for crit_item in opts_dict:
            fn = return_crit_func(crit_item, opts_dict[crit_item]['opts'])
            unit = opts_dict[crit_item]['unit']
            self.crit_lst[crit_item] = dict(
                fn=fn,
                unit=unit,
                )

    def load_state(self, ckp_load_path, load_item_lst, if_dist=True):
        """
        ckp_load_path
        -> states

        states + load_item_lst
        -> load each item from states

        Args:
            load_item_lst (example):
                ['module_gen', 'module_dis', 'optim_gen', 'optim_dis', 'sched_gen'， 'sched_dis']
            if_dist: if load for distributed training.
        """
        states = torch.load(ckp_load_path)
        for load_item in load_item_lst:
            state_dict = states[load_item]

            # load module
            if 'module_' in load_item:
                item_name = load_item[7:]
                if ('module.' in list(state_dict.keys())[0]) and if_dist:  # multi-gpu pre-trained -> single-gpu training
                    new_state_dict = OrderedDict()
                    for k, v in state_dict.items():
                        name = k[7:]  # remove module
                        new_state_dict[name] = v
                    self.model.module_lst[item_name].load_state_dict(new_state_dict)
                elif ('module.' not in list(state_dict.keys())[0]) and if_dist:  # single-gpu pre-trained -> multi-gpu training
                    new_state_dict = OrderedDict()
                    for k, v in state_dict.items():
                        name = 'module.' + k  # add module
                        new_state_dict[name] = v
                    self.model.module_lst[item_name].load_state_dict(new_state_dict)
                else:  # the same way of training
                    self.model.module_lst[item_name].load_state_dict(state_dict)
            
            # load optim
            elif 'optim_' in load_item:
                item_name = load_item[6:]
                self.optim_lst[item_name].load_state_dict(state_dict)
            
            # load sched
            elif 'sched_' in load_item:
                item_name = load_item[6:]
                self.sched_lst[item_name].load_state_dict(state_dict)
            
        return states['iter']

    def save_state(self, ckp_save_path, iter, if_sched):
        """
        ckp_save_path
        -> save iter, modules, optims and scheds to ckp_save_path as states
        """
        states = dict(iter=iter)
        for mod_item in self.model.module_lst:
            states[f'module_{mod_item}'] = self.model.module_lst[mod_item].state_dict()
        for optim_item in self.optim_lst:
            states[f'optim_{optim_item}'] = self.optim_lst[optim_item].state_dict()
        if if_sched:
            for sched_item in self.sched_lst:
                states[f'sched_{sched_item}'] = self.sched_lst[sched_item].state_dict()
        torch.save(states, ckp_save_path)

    def update_lr(self):
        """Update lrs of all scheduler."""
        for sched_item in self.sched_lst:
            self.sched_lst[sched_item].step()
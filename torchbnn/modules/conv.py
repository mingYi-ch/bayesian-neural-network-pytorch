import math

import torch
import torch.nn.init as init
from torch.nn import Module, Parameter
import torch.nn.functional as F

from torch.nn.modules.utils import _single, _pair, _triple

"""
Applies Bayesian Convolution

Arguments:
    prior_mu (Float): mean of prior normal distribution.
    prior_log_sigma (Float): log(sigma of prior normal distribution).

.. note:: other arguments are following conv of pytorch 1.2.0.
https://github.com/pytorch/pytorch/blob/master/torch/nn/modules/conv.py

"""

class _BayesConvNd(Module):

    __constants__ = ['prior_mu', 'prior_log_sigma', 'stride', 'padding', 'dilation',
                     'groups', 'bias', 'padding_mode', 'output_padding', 'in_channels',
                     'out_channels', 'kernel_size']

    def __init__(self, prior_mu, prior_log_sigma, in_channels, out_channels, kernel_size, stride,
                 padding, dilation, transposed, output_padding,
                 groups, bias, padding_mode):
        super(_BayesConvNd, self).__init__()
        if in_channels % groups != 0:
            raise ValueError('in_channels must be divisible by groups')
        if out_channels % groups != 0:
            raise ValueError('out_channels must be divisible by groups')
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.kernel_size = kernel_size
        self.stride = stride
        self.padding = padding
        self.dilation = dilation
        self.transposed = transposed
        self.output_padding = output_padding
        self.groups = groups
        self.padding_mode = padding_mode
        
        self.prior_mu = prior_mu
        self.prior_log_sigma = prior_log_sigma
        self.bias = bias
        
        
        if transposed:
            self.weight_mu = Parameter(torch.Tensor(
                in_channels, out_channels // groups, *kernel_size))
            self.weight_log_sigma = Parameter(torch.Tensor(
                in_channels, out_channels // groups, *kernel_size))
        else:
            self.weight_mu = Parameter(torch.Tensor(
                out_channels, in_channels // groups, *kernel_size))
            self.weight_log_sigma = Parameter(torch.Tensor(
                out_channels, in_channels // groups, *kernel_size))
            
        if bias:
            self.bias_mu = Parameter(torch.Tensor(out_channels))
            self.bias_log_sigma = Parameter(torch.Tensor(out_channels))
        else:
            self.register_parameter('bias_mu', None)
            self.register_parameter('bias_log_sigma', None)
            
        self.reset_parameters()

    def reset_parameters(self):
        init.kaiming_uniform_(self.weight_mu, a=math.sqrt(5))
        self.weight_log_sigma.data.fill_(self.prior_log_sigma)
        
        if self.bias :
            fan_in, _ = init._calculate_fan_in_and_fan_out(self.weight_mu)
            bound = 1 / math.sqrt(fan_in)
            init.uniform_(self.bias_mu, -bound, bound)
            
            self.bias_log_sigma.data.fill_(self.prior_log_sigma)

    def extra_repr(self):
        s = ('{prior_mu}, {prior_log_sigma}'
             ', {in_channels}, {out_channels}, kernel_size={kernel_size}'
             ', stride={stride}')
        if self.padding != (0,) * len(self.padding):
            s += ', padding={padding}'
        if self.dilation != (1,) * len(self.dilation):
            s += ', dilation={dilation}'
        if self.output_padding != (0,) * len(self.output_padding):
            s += ', output_padding={output_padding}'
        if self.groups != 1:
            s += ', groups={groups}'
        if self.bias is False:
            s += ', bias=False'
        return s.format(**self.__dict__)

    def __setstate__(self, state):
        super(_BayesConvNd, self).__setstate__(state)
        if not hasattr(self, 'padding_mode'):
            self.padding_mode = 'zeros'
    
class BayesConv2d(_BayesConvNd):
    def __init__(self, prior_mu, prior_log_sigma, in_channels, out_channels, kernel_size, stride=1, padding=0, dilation=1, groups=1, bias=True, padding_mode='zeros'):
        kernel_size = _pair(kernel_size)
        stride = _pair(stride)
        padding = _pair(padding)
        dilation = _pair(dilation)
        super(BayesConv2d, self).__init__(
            prior_mu, prior_log_sigma, in_channels, out_channels, kernel_size, stride, 
            padding, dilation, False, _pair(0), groups, bias, padding_mode)

    def conv2d_forward(self, input, weight):
        
        if self.bias:
            bias = self.bias_mu + torch.exp(self.bias_log_sigma) * torch.randn_like(self.bias_log_sigma)
        else :
            bias = None
            
        if self.padding_mode == 'circular':
            expanded_padding = ((self.padding[1] + 1) // 2, self.padding[1] // 2,
                                (self.padding[0] + 1) // 2, self.padding[0] // 2)
            return F.conv2d(F.pad(input, expanded_padding, mode='circular'),
                            weight, bias, self.stride,
                            _pair(0), self.dilation, self.groups)
        return F.conv2d(input, weight, bias, self.stride,
                        self.padding, self.dilation, self.groups)

    def forward(self, input):
        weight = self.weight_mu + torch.exp(self.weight_log_sigma) * torch.randn_like(self.weight_log_sigma)
        
        return self.conv2d_forward(input, weight)
""" 
Copyright 2019 eBay Inc.
Developers/Architects: Selcuk Kopru, Tomer Lancewicki
 
Licensed under the Apache License, Version 2.0 (the "License");
You may not use this file except in compliance with the License.
You may obtain a copy of the License at
    http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import argparse
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import datasets, transforms
from torch.autograd import Variable
from autoopt import AutoOptError
from autoopt.optim import GaussNewton, AutoSGD, AutoAdam, AutoGaussNewton


class FCNet(nn.Module):
    def __init__(self):
        nn.Module.__init__(self)
        self.fc_0 = nn.Linear(784, 320)
        self.fc_1 = nn.Linear(320, 50)
        self.fc_2 = nn.Linear(50, 10)

    def forward(self, x):
        x = x.view(-1, 784)
        self.fc_0.A_prev = x.t()
        x = F.relu(self.fc_0(x))
        self.fc_1.A_prev = x.t()
        x = F.relu(self.fc_1(x))
        self.fc_2.A_prev = x.t()
        if use_mse_loss:
            return F.softmax(self.fc_2(x), dim=1)
        else:
            return F.log_softmax(self.fc_2(x), dim=1)


class CNN(nn.Module):
    def __init__(self):
        nn.Module.__init__(self)
        self.conv1 = nn.Conv2d(1, 10, kernel_size=5)
        self.conv2 = nn.Conv2d(10, 20, kernel_size=5)
        self.conv2_drop = nn.Dropout2d()
        self.fc1 = nn.Linear(320, 50)
        self.fc2 = nn.Linear(50, 10)

    def forward(self, x):
        self.conv1.A_prev = x
        x = self.conv1(x)
        x = F.relu(F.max_pool2d(x, 2))
        self.conv2.A_prev = x
        x = self.conv2(x)
        self.conv2_drop.A_prev = x
        x = F.relu(F.max_pool2d(self.conv2_drop(x), 2))
        x = x.view(-1, 320)
        self.fc1.A_prev = x.t()
        x = F.relu(self.fc1(x))
        x = F.dropout(x, training=self.training)
        self.fc2.A_prev = x.t()
        x = self.fc2(x)
        return F.log_softmax(x, dim=1)


def get_args():
    parser = argparse.ArgumentParser(description='AutoOpt MNIST Example')
    parser.add_argument('--model', choices=['fc', 'cnn'], default='fc',
                        help='[fc] Type of NN model. fc: Fully connected NN, cnn: Convolutional NN.')
    parser.add_argument('--optimizer',
                        choices=['sgd', 'adam', 'gauss-newton', 'gn', 'auto-sgd', 'auto-adam', 'auto-gauss-newton', 'auto-gn'],
                        default='sgd', help='[sgd] Optimizer to be used in training.')
    parser.add_argument('--batch-size', type=int, default=64, metavar='N',
                        help='[64] input batch size for training.')
    parser.add_argument('--test-batch-size', type=int, default=1000, metavar='N',
                        help='[1000] Input batch size for testing.')
    parser.add_argument('--epochs', type=int, default=1, metavar='E',
                        help='[1] Number of epochs to train.')
    parser.add_argument('--ewma', type=float, default=0.9, metavar='EWMA',
                        help='[0.9] Exponential weighted moving average for the auto optimizer.')
    parser.add_argument('--gamma0', type=float, default=0.999, metavar='G',
                        help='[0.999] Initial gamma[0] value for the auto optimizer.')
    parser.add_argument('--lr', type=float, default=0.01, metavar='LR',
                        help='[0.01] Learning rate for regular optimizers.')
    parser.add_argument('--momentum', type=float, default=0.0, metavar='M',
                        help='[0.0] SGD momentum.')
    parser.add_argument('--beta-1', type=float, default=0.9, metavar='B1',
                        help='[0.9] Beta 1, Exponential decay rate for the moment estimates.')
    parser.add_argument('--beta-2', type=float, default=0.999, metavar='B2',
                        help='[0.999] Beta 2, Exponential decay rate for the moment estimates.')
    parser.add_argument('--eps', type=float, default=1e-3, metavar='E',
                        help='[1e-3] Epsilon, regularization coefficient.')
    parser.add_argument('--no-cuda', action='store_true', default=False,
                        help='[False] Disables CUDA training.')
    parser.add_argument('--seed', type=int, default=-1, metavar='S',
                        help='[-1] Random seed (-1 means no seed).')
    parser.add_argument('--log-interval', type=int, default=100, metavar='I',
                        help='[100] How many batches to wait before logging training status.')
    args = parser.parse_args()
    args.cuda = not args.no_cuda and torch.cuda.is_available()

    if args.seed != -1:
        torch.manual_seed(args.seed)

    if args.cuda:
        torch.cuda.manual_seed(args.seed)

    return args


def get_data(args):
    kwargs = {'num_workers': 1, 'pin_memory': True} if args.cuda else {}
    train_loader = torch.utils.data.DataLoader(
        datasets.MNIST('./data', train=True, download=True,
                       transform=transforms.Compose([
                           transforms.ToTensor(),
                           transforms.Normalize((0.1307,), (0.3081,))
                       ])),
        batch_size=args.batch_size, shuffle=True, **kwargs)
    test_loader = torch.utils.data.DataLoader(
        datasets.MNIST('./data', train=False, transform=transforms.Compose([
                           transforms.ToTensor(),
                           transforms.Normalize((0.1307,), (0.3081,))
                       ])),
        batch_size=args.test_batch_size, shuffle=True, **kwargs)
    return train_loader, test_loader


use_mse_loss = False


def train(epoch, model, args, train_loader, optimizer):
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        if args.cuda:
            data, target = data.cuda(), target.cuda()
        data, target = Variable(data), Variable(target)
        optimizer.zero_grad()
        output = model(data)

        if args.optimizer in ['sgd', 'adam', 'adagrad']:
            loss = F.nll_loss(output, target)
        else:
            model.loss_all = F.nll_loss(output, target, reduction='none')
            loss = torch.mean(model.loss_all)

        if torch.isnan(loss):
            import sys
            sys.exit()

        loss.backward()
        optimizer.step()

        if batch_idx % args.log_interval == 0:
            print('Train Epoch: {} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                epoch, batch_idx * len(data), len(train_loader.dataset),
                100. * batch_idx / len(train_loader), loss))


def test(model, args, test_loader):
    model.eval()
    test_loss = 0
    correct = 0
    for data, target in test_loader:
        if args.cuda:
            data, target = data.cuda(), target.cuda()
        data, target = Variable(data), Variable(target)
        output = model(data)
        test_loss += F.nll_loss(output, target) # sum up batch loss
        pred = output.data.max(1, keepdim=True)[1] # get the index of the max log-probability
        correct += pred.eq(target.data.view_as(pred)).cpu().sum()

    test_loss /= len(test_loader.dataset)
    print('\nTest set: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)\n'.format(
        test_loss, correct, len(test_loader.dataset),
        100. * correct / len(test_loader.dataset)))


def main():
    args = get_args()
    train_loader, test_loader = get_data(args)
    if args.model == 'fc':
        model = FCNet()
    elif args.model == 'cnn':
        model = CNN()
    else:
        raise AutoOptError('Error: Unknown model type: {0}'.format(args.model))

    if args.cuda:
        model.cuda()

    if args.optimizer == 'sgd':
        optimizer = torch.optim.SGD(model.parameters(), lr=args.lr, momentum=args.momentum, dampening=args.momentum)
    elif args.optimizer == 'auto-sgd':
        optimizer = AutoSGD(model)
    elif args.optimizer == 'adam':
        optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, betas=(args.beta_1, args.beta_2), eps=args.eps)
    elif args.optimizer == 'auto-adam':
        optimizer = AutoAdam(model)
    elif args.optimizer == 'gauss-newton' or args.optimizer == 'gn':
        optimizer = GaussNewton(model, lr=args.lr, betas=(args.beta_1, args.beta_2), eps=args.eps)
    elif args.optimizer == 'auto-gauss-newton' or args.optimizer == 'auto-gn':
        optimizer = AutoGaussNewton(model, beta2=args.beta_2, eps=args.eps)
    else:
        raise AutoOptError('Error: Unknown optimizer: {0}'.format(args.optimizer))

    for epoch in range(1, args.epochs + 1):
        train(epoch, model, args, train_loader, optimizer)
        test(model, args, test_loader)


if __name__ == '__main__':
    main()

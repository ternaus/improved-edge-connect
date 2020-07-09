import torch
import torch.nn as nn


class ILN(nn.Module):
    def __init__(self, num_features: int, eps: float = 1.1e-5):
        super().__init__()
        self.eps = eps
        self.rho = nn.Parameter(torch.Tensor(1, num_features, 1, 1))
        self.gamma = nn.Parameter(torch.Tensor(1, num_features, 1, 1))
        self.beta = nn.Parameter(torch.Tensor(1, num_features, 1, 1))
        self.rho.data.fill_(0.0)
        self.gamma.data.fill_(1.0)
        self.beta.data.fill_(0.0)

    def forward(self, x):
        in_mean, in_var = torch.mean(x, dim=[2, 3], keepdim=True), torch.var(x, dim=[2, 3], keepdim=True)
        out_in = (x - in_mean) / torch.sqrt(in_var + self.eps)
        ln_mean, ln_var = torch.mean(x, dim=[1, 2, 3], keepdim=True), torch.var(x, dim=[1, 2, 3], keepdim=True)
        out_ln = (x - ln_mean) / torch.sqrt(ln_var + self.eps)
        out = self.rho.expand(x.shape[0], -1, -1, -1) * out_in + (1 - self.rho.expand(x.shape[0], -1, -1, -1)) * out_ln
        out = out * self.gamma.expand(x.shape[0], -1, -1, -1) + self.beta.expand(x.shape[0], -1, -1, -1)
        return out


class BaseNetwork(nn.Module):
    def __init__(self):
        super().__init__()

    def init_weights(self, init_type: str = "normal", gain: float = 2e-2) -> None:
        """
        initialize network's weights
        init_type: normal | xavier | kaiming | orthogonal
        https://github.com/junyanz/pytorch-CycleGAN-and-pix2pix/blob/9451e70673400885567d08a9e97ade2524c700d0/models/networks.py#L39
        """

        def init_func(m):
            classname = m.__class__.__name__
            if hasattr(m, "weight") and (classname.find("Conv") != -1 or classname.find("Linear") != -1):
                if init_type == "normal":
                    nn.init.normal_(m.weight.data, 0.0, gain)
                elif init_type == "xavier":
                    nn.init.xavier_normal_(m.weight.data, gain=gain)
                elif init_type == "kaiming":
                    nn.init.kaiming_normal_(m.weight.data, a=0, mode="fan_in")
                elif init_type == "orthogonal":
                    nn.init.orthogonal_(m.weight.data, gain=gain)

                if hasattr(m, "bias") and m.bias is not None:
                    nn.init.constant_(m.bias.data, 0.0)

            elif classname.find("BatchNorm2d") != -1:
                nn.init.normal_(m.weight.data, 1.0, gain)
                nn.init.constant_(m.bias.data, 0.0)

        self.apply(init_func)


class InpaintGenerator(BaseNetwork):
    def __init__(self, residual_blocks: int = 8, init_weights: bool = True) -> None:
        super().__init__()

        self.encoder = nn.Sequential(
            nn.ReflectionPad2d(3),
            nn.Conv2d(in_channels=4, out_channels=64, kernel_size=7, padding=0),
            nn.InstanceNorm2d(64, track_running_stats=False),
            nn.ReLU(True),
            nn.Conv2d(in_channels=64, out_channels=128, kernel_size=4, stride=2, padding=1),
            nn.InstanceNorm2d(128, track_running_stats=False),
            nn.ReLU(True),
            nn.Conv2d(in_channels=128, out_channels=256, kernel_size=4, stride=2, padding=1),
            nn.InstanceNorm2d(256, track_running_stats=False),
            nn.ReLU(True),
        )

        blocks = [ResBlock(256, 2) for _ in range(residual_blocks)]

        self.middle = nn.Sequential(*blocks)

        self.decoder = nn.Sequential(
            nn.ConvTranspose2d(in_channels=256, out_channels=128, kernel_size=4, stride=2, padding=1),
            nn.InstanceNorm2d(128, track_running_stats=False),
            nn.ReLU(True),
            nn.ConvTranspose2d(in_channels=128, out_channels=64, kernel_size=4, stride=2, padding=1),
            nn.InstanceNorm2d(64, track_running_stats=False),
            nn.ReLU(True),
            nn.ReflectionPad2d(3),
            nn.Conv2d(in_channels=64, out_channels=3, kernel_size=7, padding=0),
        )

        if init_weights:
            self.init_weights()

    def forward(self, x):
        x = self.encoder(x)
        x = self.middle(x)
        x = self.decoder(x)
        x = (torch.tanh(x) + 1) / 2
        return x


class EdgeGenerator(BaseNetwork):
    def __init__(self, residual_blocks: int = 8, use_spectral_norm: bool = True, init_weights: bool = True) -> None:
        super().__init__()

        self.encoder = nn.Sequential(
            nn.ReflectionPad2d(3),
            spectral_norm(nn.Conv2d(in_channels=3, out_channels=64, kernel_size=7, padding=0), use_spectral_norm),
            nn.ReLU(True),
            spectral_norm(
                nn.Conv2d(in_channels=64, out_channels=128, kernel_size=4, stride=2, padding=1), use_spectral_norm
            ),
            nn.InstanceNorm2d(128),
            nn.ReLU(True),
            spectral_norm(
                nn.Conv2d(in_channels=128, out_channels=256, kernel_size=4, stride=2, padding=1), use_spectral_norm
            ),
            nn.InstanceNorm2d(256),
            nn.ReLU(True),
        )

        blocks = [ResBlock(256, 2, use_spectral_norm=use_spectral_norm) for _ in range(residual_blocks)]

        self.middle = nn.Sequential(*blocks)

        self.alter_decoder = nn.Sequential(
            nn.Upsample(scale_factor=2),
            nn.ReflectionPad2d(1),
            spectral_norm(
                nn.Conv2d(in_channels=256, out_channels=128, kernel_size=3, stride=1, padding=0), use_spectral_norm
            ),
            ILN(128),
            nn.ReLU(True),
            nn.Upsample(scale_factor=2),
            nn.ReflectionPad2d(1),
            spectral_norm(
                nn.Conv2d(in_channels=128, out_channels=64, kernel_size=3, stride=1, padding=0), use_spectral_norm
            ),
            ILN(64),
            nn.ReLU(True),
            nn.ReflectionPad2d(3),
            nn.Conv2d(in_channels=64, out_channels=1, kernel_size=7, padding=0),
        )

        self.decoder = nn.Sequential(
            spectral_norm(
                nn.ConvTranspose2d(in_channels=256, out_channels=128, kernel_size=4, stride=2, padding=1),
                use_spectral_norm,
            ),
            nn.InstanceNorm2d(128),
            nn.ReLU(True),
            spectral_norm(
                nn.ConvTranspose2d(in_channels=128, out_channels=64, kernel_size=4, stride=2, padding=1),
                use_spectral_norm,
            ),
            nn.InstanceNorm2d(64),
            nn.ReLU(True),
            nn.ReflectionPad2d(3),
            nn.Conv2d(in_channels=64, out_channels=1, kernel_size=7, padding=0),
        )

        if init_weights:
            self.init_weights()

    def forward(self, x: torch.Tensor, use_alter_decoder: bool = True) -> torch.Tensor:
        x_init = x
        x = self.encoder(x)
        x = self.middle(x)
        x = self.alter_decoder(x) if use_alter_decoder else self.decoder(x)
        x = torch.sigmoid(x)
        masked_edge = torch.chunk(x_init, 3, dim=1)[1]
        return x + masked_edge


class Discriminator(BaseNetwork):
    def __init__(
        self, in_channels: int, use_sigmoid: bool = True, use_spectral_norm: bool = True, init_weights: bool = True
    ) -> None:
        super().__init__()
        self.use_sigmoid = use_sigmoid

        self.conv1 = self.features = nn.Sequential(
            nn.ReflectionPad2d(1),
            spectral_norm(
                nn.Conv2d(
                    in_channels=in_channels,
                    out_channels=64,
                    kernel_size=4,
                    stride=2,
                    padding=0,
                    bias=not use_spectral_norm,
                ),
                use_spectral_norm,
            ),
            nn.LeakyReLU(0.2, True),
        )

        self.conv2 = nn.Sequential(
            nn.ReflectionPad2d(1),
            spectral_norm(
                nn.Conv2d(
                    in_channels=64, out_channels=128, kernel_size=4, stride=2, padding=0, bias=not use_spectral_norm
                ),
                use_spectral_norm,
            ),
            nn.LeakyReLU(0.2, True),
        )

        self.conv3 = nn.Sequential(
            nn.ReflectionPad2d(1),
            spectral_norm(
                nn.Conv2d(
                    in_channels=128, out_channels=256, kernel_size=4, stride=2, padding=0, bias=not use_spectral_norm
                ),
                use_spectral_norm,
            ),
            nn.LeakyReLU(0.2, True),
        )

        self.conv4 = nn.Sequential(
            nn.ReflectionPad2d(1),
            spectral_norm(
                nn.Conv2d(
                    in_channels=256, out_channels=512, kernel_size=4, stride=1, padding=0, bias=not use_spectral_norm
                ),
                use_spectral_norm,
            ),
            nn.LeakyReLU(0.2, True),
        )

        self.conv5 = nn.Sequential(
            nn.ReflectionPad2d(1),
            spectral_norm(
                nn.Conv2d(
                    in_channels=512, out_channels=1, kernel_size=4, stride=1, padding=0, bias=not use_spectral_norm
                ),
                use_spectral_norm,
            ),
        )

        if init_weights:
            self.init_weights()

    def forward(self, x):
        conv1 = self.conv1(x)
        conv2 = self.conv2(conv1)
        conv3 = self.conv3(conv2)
        conv4 = self.conv4(conv3)
        conv5 = self.conv5(conv4)

        outputs = conv5
        if self.use_sigmoid:
            outputs = torch.sigmoid(conv5)

        return outputs, [conv1, conv2, conv3, conv4, conv5]


class ResBlock(nn.Module):
    def __init__(self, dim: int, dilation: int = 1, use_spectral_norm: bool = False) -> None:
        super().__init__()
        self.conv_block = nn.Sequential(
            nn.ReflectionPad2d(dilation),
            spectral_norm(
                nn.Conv2d(
                    in_channels=dim,
                    out_channels=dim,
                    kernel_size=3,
                    padding=0,
                    dilation=dilation,
                    bias=not use_spectral_norm,
                ),
                use_spectral_norm,
            ),
            nn.InstanceNorm2d(dim),
            nn.ReLU(True),
            nn.ReflectionPad2d(1),
            spectral_norm(
                nn.Conv2d(
                    in_channels=dim, out_channels=dim, kernel_size=3, padding=0, dilation=1, bias=not use_spectral_norm
                ),
                use_spectral_norm,
            ),
            nn.InstanceNorm2d(dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Remove ReLU at the end of the residual block
        # http://torch.ch/blog/2016/02/04/resnets.html
        return x + self.conv_block(x)


def spectral_norm(module: nn.Module, mode: bool = True) -> nn.Module:
    if mode:
        return nn.utils.spectral_norm(module)
    return module


class RhoClipper:
    def __init__(self, clip_min: float, clip_max: float) -> None:
        self.clip_min = clip_min
        self.clip_max = clip_max
        assert clip_min < clip_max

    def __call__(self, module: nn.Module) -> None:
        if hasattr(module, "rho"):
            w = module.rho.data
            w = w.clamp(self.clip_min, self.clip_max)
            module.rho.data = w

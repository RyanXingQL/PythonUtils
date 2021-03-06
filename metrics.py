import torch
import numpy as np
from scipy import stats
import torch.nn as nn

# Criteria

crit_lst = ['PSNR', 'LPIPS']


def return_crit_func(name, opts):
    assert (name in crit_lst), 'NOT SUPPORTED YET!'
    crit_func_cls = globals()[name]
    if opts is not None:
        return crit_func_cls(**opts)
    else:
        return crit_func_cls()


class PSNR(nn.Module):
    """Input tensor. Return a float."""

    def __init__(self):
        super().__init__()

        self.mse_func = nn.MSELoss()
        self.lsb = False  # lower is better

    def forward(self, x, y):
        mse = self.mse_func(x, y)
        psnr = 10 * torch.log10(1. / mse)
        return psnr.item()


class LPIPS(nn.Module):
    """Learned Perceptual Image Patch Similarity.

    Args:
        if_spatial: return a score or a map of scores.

    https://github.com/richzhang/PerceptualSimilarity
    """

    def __init__(self, net='alex', if_spatial=False, if_cuda=True):
        super().__init__()
        import lpips

        self.lpips_fn = lpips.LPIPS(net=net, spatial=if_spatial)
        if if_cuda:
            self.lpips_fn.cuda()

        self.lsb = True

    @staticmethod
    def _preprocess(inp, mode):
        out = None
        if mode == 'im':
            im = inp[:, :, ::-1]  # (H W BGR) -> (H W RGB)
            im = im / (255. / 2.) - 1.
            im = im[..., np.newaxis]  # (H W RGB 1)
            im = im.transpose(3, 2, 0, 1)  # (B=1 C=RGB H W)
            out = torch.Tensor(im)
        elif mode == 'tensor':
            out = inp * 2. - 1.
        return out

    def forward(self, ref, im):
        """
        im: cv2 loaded images, or ([RGB] H W), [0, 1] CUDA tensor.
        """
        mode = 'im' if ref.dtype == np.uint8 else 'tensor'
        ref = self._preprocess(ref, mode=mode)
        im = self._preprocess(im, mode=mode)
        lpips_score = self.lpips_fn.forward(ref, im)
        return lpips_score.item()


# Others

class PCC:
    """Pearson correlation coefficient."""

    def __init__(self):
        self.help = (
            'Pearson correlation coefficient measures linear correlation '
            'between two variables X and Y. '
            'It has a value between +-1. '
            '+1: total positive linear correlation. '
            '0: no linear correlation. '
            '-1: total negative linear correlation. '
            'See: https://en.wikipedia.org/wiki/Pearson_correlation_coefficient'
        )

    @staticmethod
    def cal_pcc_two_imgs(x, y):
        """Calculate Pearson correlation coefficient of two images.

        Consider each pixel in x as a sample from a variable X, each pixel in y
        as a sample from a variable Y. Then an mxn image equals to mxn times
        sampling.

        Input:
            x, y: two imgs (numpy array).
        Return:
            (cc value, p-value)

        Formula: https://docs.scipy.org/doc/scipy/reference/generated
        /scipy.stats.pearsonr.html?highlight=pearson#scipy.stats.pearsonr

        Note: x/y should not be a constant! Else, the sigma will be zero,
        and the cc value will be not defined (nan).
        """
        return stats.pearsonr(x.reshape((-1,)), y.reshape((-1,)))

    def _test(self):
        x = np.array([[3, 4], [1, 1]], dtype=np.float32)
        y = x + np.ones((2, 2), dtype=np.float32)
        print(self.cal_pcc_two_imgs(x, y))

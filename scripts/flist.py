import os
from glob import glob

import numpy as np
from tqdm import tqdm

mode: str = "val"
data_type: str = "mask"  # image
output: str = "../datasets/"

images = []
if data_type == "image":
    # pure_bald_paths = np.load('pure_bald.npy')
    if mode == "test":
        root = "/media/zero/awesome/Human/x256/orig/"
        images = sorted([os.path.join(root, mode, fn) for fn in tqdm(glob(os.path.join(root, "*")))])
    else:
        root = "/media/zero/awesome/Bald/x256/"
        images = sorted([os.path.join(root, mode, fn) for fn in tqdm(glob(os.path.join(root, mode, "*")))])

    np.savetxt(os.path.join(output, "bald_%s.flist" % mode), images, fmt="%s")
elif data_type == "mask":
    images = sorted(glob(os.path.join("/media/zero/awesome/Mask/x256/", mode, "*")))
    np.savetxt(os.path.join(output, "bald_masks_%s.flist" % mode), images, fmt="%s")
elif data_type == "edge":
    np.savetxt(os.path.join(output, "bald_edges_%s.flist" % mode), images, fmt="%s")
else:
    raise NotImplementedError

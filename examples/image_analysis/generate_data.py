"""Data generator for the image-analysis example arc.

Trains a small RandomForest pixel classifier on skimage's ``skin()`` sample
photo (same basis as the scikit-image trainable-segmentation tutorial),
predicts per-pixel class probabilities, then tiles image+probabilities into
``data/{s,m,l}``. Writes both the CSV-per-class form (used by step A) and the
HDF5 form (used by steps B–F).
"""

from __future__ import annotations

import argparse
import functools
from collections.abc import Iterable
from pathlib import Path
from shutil import rmtree

import h5py
import numpy as np
import skimage
from sklearn.ensemble import RandomForestClassifier

# Tiling scale factors per size key.
SIZES: dict[str, int] = {"s": 1, "m": 2, "l": 4}

# Training-label boxes, recorded as pixel boxes against a 900x900 reference
# crop and scaled proportionally so smaller --crop-size values (quick demo /
# test data) still produce all 4 classes.
_REFERENCE_CROP = 900
_LABEL_BOXES: list[tuple[slice, slice, int]] = [
    (slice(0, 130), slice(None, None), 1),
    (slice(0, 170), slice(0, 400), 1),
    (slice(600, 900), slice(200, 650), 2),
    (slice(330, 430), slice(210, 320), 3),
    (slice(260, 340), slice(60, 170), 4),
    (slice(150, 200), slice(720, 860), 4),
]


def _scaled_slice(s: slice, crop_size: int) -> slice:
    def scale(v: int | None) -> int | None:
        return None if v is None else round(v * crop_size / _REFERENCE_CROP)

    return slice(scale(s.start), scale(s.stop))


def make_training_labels(crop_size: int) -> np.ndarray:
    labels = np.zeros((crop_size, crop_size), dtype=np.uint8)
    for row_slice, col_slice, class_id in _LABEL_BOXES:
        labels[
            _scaled_slice(row_slice, crop_size), _scaled_slice(col_slice, crop_size)
        ] = class_id
    return labels


def train(crop_size: int = _REFERENCE_CROP):
    img = skimage.data.skin()[:crop_size, :crop_size]
    training_labels = make_training_labels(crop_size)

    features_func = functools.partial(
        skimage.feature.multiscale_basic_features,
        intensity=True,
        edges=False,
        texture=True,
        sigma_min=1,
        sigma_max=16,
        channel_axis=-1,
    )
    features = features_func(img)
    classifier = RandomForestClassifier(
        n_estimators=50, n_jobs=-1, max_depth=10, max_samples=0.05
    )
    classifier = skimage.future.fit_segmenter(training_labels, features, classifier)
    return features_func, classifier, img


def predict_probabilities(image: np.ndarray, features_func, classifier) -> np.ndarray:
    features = features_func(image)
    features_flat = features.reshape((-1, features.shape[-1]))
    probabilities_flat = classifier.predict_proba(features_flat)
    probabilities = probabilities_flat.reshape(features.shape[:-1] + (-1,))
    return probabilities


def save_image_and_probabilities(
    folder: Path, image: np.ndarray, probabilities: np.ndarray
) -> None:
    rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    with h5py.File(folder / "data.hdf5", "w") as f:
        f.create_dataset("image", data=image)
        f.create_dataset("probabilities", data=probabilities)
    for c in range(probabilities.shape[-1]):
        np.savetxt(folder / f"{c}.csv", probabilities[..., c])


def generate(
    out_dir: Path,
    sizes: dict[str, int] | None = None,
    crop_size: int = _REFERENCE_CROP,
) -> None:
    """Train once, then tile+write every requested size into ``out_dir/<key>``.

    Small ``crop_size`` values (e.g. 100) keep the whole cycle sub-second for
    quick demo or test data; the default 900 matches the full-resolution photo.
    """
    if sizes is None:
        sizes = SIZES
    features_func, classifier, image = train(crop_size=crop_size)
    probabilities = predict_probabilities(image, features_func, classifier)
    for key, scale in sizes.items():
        reps = (scale, scale, 1)
        image_tiled = np.tile(image, reps)
        probabilities_tiled = np.tile(probabilities, reps)
        save_image_and_probabilities(out_dir / key, image_tiled, probabilities_tiled)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        nargs="+",
        default=list(SIZES),
        choices=list(SIZES),
        help="which size keys to generate (default: s m l)",
    )
    parser.add_argument(
        "--crop-size",
        type=int,
        default=_REFERENCE_CROP,
        help="base crop of the sample photo (default 900; small values make quick demo data)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "data",
        help="output root (default: <this dir>/data)",
    )
    args = parser.parse_args(argv)
    sizes: Iterable[str] = args.sizes
    generate(args.out, sizes={k: SIZES[k] for k in sizes}, crop_size=args.crop_size)


if __name__ == "__main__":
    main()

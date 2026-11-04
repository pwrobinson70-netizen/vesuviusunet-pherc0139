# Public real-data test sample: PHerc. Paris 4 (Scroll 1), CT + SURFACE PREDICTION on one grid, cropped window

Licence: CC BY-NC 4.0 (Vesuvius Challenge open data; see https://scrollprize.org/data). Non-commercial test sample only.

CT: https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr level 2 (level-0 shape [75784, 32693, 32693], this level [18946, 8174, 8174]); voxel ~9.60 um.
Surface prediction: https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/representations/predictions/surfaces/20260411134726-surface-20260413222639-surface-m7-L2-th0.2.zarr level 0 (shape [18946, 8174, 8174], dtype uint8); 8-bit PNG, higher = more papyrus-like.
Window: x 6625:7649, y 3274:4298; slices/ and surfpred/ share this window and the heights [9503, 12001, 14499].
Meshes: adjacent windings 20260623164704-w116-117 and 20260623165230-w118-119 from the 2.4 um tifxyz, coordinates divided by 4.000, cropped, z-trimmed to [9439,14563], grid subsampled 4x (see crop_note), and shifted by -(6625,3274); meta scale updated.

| file | sha256 | source |
|---|---|---|
| slices/09503.png | fee27c78e0b5e9290022307233b9da3202ffc1d5b194bf197ab64a571509fb5c | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr/2 (z=9503, y 3274:4298, x 6625:7649) |
| surfpred/09503.png | ef5703bb5335917750cfe7ec282d614c320c32ae3f1f885a0bc2b5cebca9bb92 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/representations/predictions/surfaces/20260411134726-surface-20260413222639-surface-m7-L2-th0.2.zarr/0 (z=9503, y 3274:4298, x 6625:7649) |
| slices/12001.png | e57729d94afad976d667c885e9d9a1accd1b3fee470dfe689cd656aa6d4e3de6 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr/2 (z=12001, y 3274:4298, x 6625:7649) |
| surfpred/12001.png | 513fcd65d4669b22f5c166e7e86df2c91ad2d9ee6bf6ed990b93f96ba3cf120d | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/representations/predictions/surfaces/20260411134726-surface-20260413222639-surface-m7-L2-th0.2.zarr/0 (z=12001, y 3274:4298, x 6625:7649) |
| slices/14499.png | 1334c18d9d05a5c15af4f1ade58e93d4f57198613d066d1816d07c760f2657e6 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/volumes/20260411134726-2.400um-0.2m-78keV-masked.zarr/2 (z=14499, y 3274:4298, x 6625:7649) |
| surfpred/14499.png | 54b3518aa313f08e057e0e14387ed0bfae64f405b90daaaa33635f0786599415 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/representations/predictions/surfaces/20260411134726-surface-20260413222639-surface-m7-L2-th0.2.zarr/0 (z=14499, y 3274:4298, x 6625:7649) |
| 20260623164704-w116-117.tifxyz/meta.json | 316bc95550d557d851caa6030399eb04b32617d74b7717a3087314a93a483928 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623164704-w116-117/mesh/20260623164704-on-20260411134726-2.4um.tifxyz/meta.json (scaled 1/4.00, cropped) |
| 20260623164704-w116-117.tifxyz/x.tif | 0b50c449ea24078d077bc7f97e7040fe1c28ff2325b06ceb8396f7dfe64d80cc | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623164704-w116-117/mesh/20260623164704-on-20260411134726-2.4um.tifxyz/x.tif (scaled 1/4.00, cropped) |
| 20260623164704-w116-117.tifxyz/y.tif | 27bb02f15e818e715a886074d8c1b82b3ad24a838e62151dc489a1014a39e644 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623164704-w116-117/mesh/20260623164704-on-20260411134726-2.4um.tifxyz/y.tif (scaled 1/4.00, cropped) |
| 20260623164704-w116-117.tifxyz/z.tif | 427a82824ee4389750821bb345ef5c92820078ccc7a5dcb25d89d32d830c354d | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623164704-w116-117/mesh/20260623164704-on-20260411134726-2.4um.tifxyz/z.tif (scaled 1/4.00, cropped) |
| 20260623165230-w118-119.tifxyz/meta.json | f09e576688d753fe674481ba101f8d4672751492936eb89560a76d0b768be108 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623165230-w118-119/mesh/20260623165230-on-20260411134726-2.4um.tifxyz/meta.json (scaled 1/4.00, cropped) |
| 20260623165230-w118-119.tifxyz/x.tif | a1d51d5ee92aad3aa68e395ee9e555fb1df2558ad899cac6283d89114c676a91 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623165230-w118-119/mesh/20260623165230-on-20260411134726-2.4um.tifxyz/x.tif (scaled 1/4.00, cropped) |
| 20260623165230-w118-119.tifxyz/y.tif | 5c4688311ddd351fb9c433ef2842cdd426ea6886133b15305f6b5592cb502730 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623165230-w118-119/mesh/20260623165230-on-20260411134726-2.4um.tifxyz/y.tif (scaled 1/4.00, cropped) |
| 20260623165230-w118-119.tifxyz/z.tif | c354af90cd4cda827ccfb90d3b51602fba2caa47c847da981fc47f77ac87b15a | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623165230-w118-119/mesh/20260623165230-on-20260411134726-2.4um.tifxyz/z.tif (scaled 1/4.00, cropped) |

Total size: 13.4 MB

Fetched by fetch_public_sample_surfpred_fable_03112026.py. No First Letters scroll was used.

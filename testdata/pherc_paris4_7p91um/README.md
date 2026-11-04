# Public real-data test sample: PHerc. Paris 4 (Scroll 1), 7.91 um volume, CROPPED window

Licence: CC BY-NC 4.0 (Vesuvius Challenge open data; see https://scrollprize.org/data). Non-commercial test sample only.

Volume: https://data.aws.ash2txt.org/samples/PHercParis4/volumes/20230205180739-7.910um-54keV-masked.zarr (level 0, shape [14258, 7888, 8096], chunks [128, 128, 128], dtype uint8). Voxel 7.91 um.
Window: x 614:2150, y 0:1536 (volume voxels). Slice PNGs are this window only, 8-bit.
Meshes: adjacent windings 20260623164704-w116-117 and 20260623165230-w118-119, cropped to the window and SHIFTED by -(614,0) in x,y so the PNGs act as a volume with origin 0; z unchanged.
Slice heights (z): [2644, 5729, 8814]

| file | sha256 | source |
|---|---|---|
| slices/02644.png | 754092210ebcf0791a77f775c90aef1a0eca4dc4bc73ae5ccc24d66283cf5162 | https://data.aws.ash2txt.org/samples/PHercParis4/volumes/20230205180739-7.910um-54keV-masked.zarr/0 (z=2644, y 0:1536, x 614:2150) |
| slices/05729.png | b46dc6c413b55ac0a29430f37d5885eb8803b72bf18b333e98268b034aece751 | https://data.aws.ash2txt.org/samples/PHercParis4/volumes/20230205180739-7.910um-54keV-masked.zarr/0 (z=5729, y 0:1536, x 614:2150) |
| slices/08814.png | 468a2d8eaf5362533ccdebf313f696d67fff52e108e767521709d1a296de3a74 | https://data.aws.ash2txt.org/samples/PHercParis4/volumes/20230205180739-7.910um-54keV-masked.zarr/0 (z=8814, y 0:1536, x 614:2150) |
| 20260623164704-w116-117.tifxyz/meta.json | b5d7ceb09607c4907f30766a239c45702a1550d879e7799769c1cad9b009178a | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623164704-w116-117/mesh/20260623164704-on-20230205180739-7.91um.tifxyz/meta.json (cropped) |
| 20260623164704-w116-117.tifxyz/x.tif | 1bd88c1ad66f08026fd2dafa859c842d0aadcddb7256e9dcceca0211971f7892 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623164704-w116-117/mesh/20260623164704-on-20230205180739-7.91um.tifxyz/x.tif (cropped) |
| 20260623164704-w116-117.tifxyz/y.tif | 4fb43367eda2ababec14630e61468927b4452c1959dacc436d6890e9fd327df2 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623164704-w116-117/mesh/20260623164704-on-20230205180739-7.91um.tifxyz/y.tif (cropped) |
| 20260623164704-w116-117.tifxyz/z.tif | 6fee7e51e29e1a429e8beb9309b46643895735d76e3532e2164ab882930c0097 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623164704-w116-117/mesh/20260623164704-on-20230205180739-7.91um.tifxyz/z.tif (cropped) |
| 20260623165230-w118-119.tifxyz/meta.json | ca3eb1ffe92dbbff4eff62d02b01d2f8517364760b0cf52293f6edf32233bcd4 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623165230-w118-119/mesh/20260623165230-on-20230205180739-7.91um.tifxyz/meta.json (cropped) |
| 20260623165230-w118-119.tifxyz/x.tif | e606e1f2f72f24fdfd67fe07c40a3613be0f4190708ee2b268c57ac5d577f32c | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623165230-w118-119/mesh/20260623165230-on-20230205180739-7.91um.tifxyz/x.tif (cropped) |
| 20260623165230-w118-119.tifxyz/y.tif | 7d7d08db2c107aa1b3ef9b02dcb7b6721c54ab39c5dcf905b262314a62ec9a37 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623165230-w118-119/mesh/20260623165230-on-20230205180739-7.91um.tifxyz/y.tif (cropped) |
| 20260623165230-w118-119.tifxyz/z.tif | 9395e64d1cf74438d5d760e170c26d4fdb2b7dd3d30d4a412dbd0ff5661290f3 | https://vesuvius-challenge-open-data.s3.amazonaws.com/PHercParis4/segments/20260623165230-w118-119/mesh/20260623165230-on-20230205180739-7.91um.tifxyz/z.tif (cropped) |

Total size: 35.9 MB

Fetched by fetch_public_sample_hires_fable_03112026.py. No First Letters scroll was used.

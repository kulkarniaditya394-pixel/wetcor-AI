# Showcase example (pre-computed test)

Loaded from the app: **Showcase → Load showcase example**. Removed by Settings → Reset demo workspace.
Everything shown is computed by WETCOR AI from the files below; `showcase.json` only supplies inputs.

| File | What it is |
|---|---|
| `source_attension_theta_frame.png` | "Contact angle measurement with Attension Theta" by **Jyrkorpela**, [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Contact_angle_measurement_with_Attension_Theta.png), licensed **[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)**. Unmodified. Substrate not documented by the author. |
| `droplet_for_analysis.png` | Adaptation of the file above (crop to the camera viewport + inpainting of the third-party orange overlay), produced by `scripts/prepare_showcase_image.py`. Licensed **CC BY-SA 4.0** like the original. |
| `ocp_SYNTHETIC.csv`, `polarisation_SYNTHETIC.txt` | SYNTHETIC electrochemistry (E_corr −0.62 V, i_corr 8 µA/cm², β_a 70, β_c 130 mV/dec) for a steel-like specimen. Not measurements. |
| `showcase.json` | Inputs: specimen and conditions, baseline placement, Tafel regions, material profile, and the instrument's own reading shown in the source frame (114.95° / 114.29°) for comparison. |

No openly licensed side-view photograph of a droplet on a steel plate was found; top-down photos of droplets on
steel cannot be used to measure a contact angle. **To make the showcase your own steel-plate test:** replace the image
and electrochemistry files with your own, edit `showcase.json` (file names, baseline, regions, specimen fields,
remove `source`/`reference` or fill them with your data), then *Reset demo workspace* and *Load showcase example* again.

The `ISS_preprocessing` module aims to transform files extracted from the microscope, into image files that can be used for decoding. Although the images from the microscopes represent a 3D space, our analysis works on 2D images. For this reason, the first step we'll do is a maximum Z-projection of the 3D images obtained from the microscope. The resulting 2D projected images ("tiles") are stitched and the stitched images are then aligned between cycles. Finally, for computational reasons, we slice the aligned big tiffs obtained into smaller (aligned between cycles) tiles, which will be the perfect input to start decoding our samples. 

conda env create -f environment.yml




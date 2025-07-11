from xml.dom import minidom
from tqdm import tqdm
import os
import pandas as pd
import tifffile
import numpy as np
import re
import shutil
from os.path import join
import ISS_processing.preprocessing as preprocessing
import ashlar.scripts.ashlar as ashlar
import cv2
import math
import mat73
import pathlib
import xml.etree.ElementTree as ET
from aicspylibczi import CziFile
import requests
from readlif.reader import LifFile
import xml.etree.ElementTree as ET
from natsort import natsorted


def customcopy(src, dst):
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    shutil.copyfile(src, dst)


def zen_OME_tiff(exported_directory, output_directory, channel_split=2, cycle_split=1, num_channels=5):
    '''
    This function makes OME-TIFF files from files exported from as tiff from ZEN, through the process_czi or to the deconvolve_czi functions.
    Note: Assumes Nilsson SOP naming. Works on 1-tile sections.
    '''
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
    all_files = os.listdir(exported_directory)
    tiff_files = [f for f in all_files if f.endswith('.tif')]
    split_tiles_df = pd.DataFrame(tiff_files)[0].str.split('m', expand=True)
    split_ch_df = split_tiles_df[0].str.split('_', expand=True)
    tiles = list(np.unique(split_tiles_df[1]))
    channels = list(np.unique(split_ch_df[channel_split]))
    rounds = list(np.unique(split_ch_df[cycle_split]))

    for rnd in rounds:
        files_rnd = [f for f in tiff_files if f'Base_{rnd}_' in f]
        meta_files = [f for f in all_files if 'info.xml' in f and f'_{rnd}_' in f]
        for mfile in meta_files:
            doc = minidom.parse(join(exported_directory, mfile))
            tiles_xml, xs, ys = [], [], []
            for b in doc.getElementsByTagName('Bounds'):
                tiles_xml.append(int(b.attributes['StartM'].value))
                xs.append(float(b.attributes['StartX'].value))
                ys.append(float(b.attributes['StartY'].value))
            uniq = list(np.unique(tiles_xml))
            pos_df = pd.DataFrame({'x': xs[:len(uniq)], 'y': ys[:len(uniq)]})
            positions = np.array(pos_df).astype(int)

        with tifffile.TiffWriter(join(output_directory, f'cycle_{rnd}.ome.tif'), bigtiff=True) as tif:
            for i, tile in enumerate(tiles):
                pos = positions[i]
                tile_files = [f for f in files_rnd if f'm{tile}' in f and not f.startswith('._')]
                stack = np.empty((num_channels, 2048, 2048), dtype='uint16')
                for idx, imgf in enumerate(sorted(tile_files)):
                    img = tifffile.imread(join(exported_directory, imgf))
                    stack[idx] = img.astype('uint16')
                pix = 0.1625
                meta = {
                    'Pixels': {
                        'PhysicalSizeX': pix, 'PhysicalSizeXUnit': 'µm',
                        'PhysicalSizeY': pix, 'PhysicalSizeYUnit': 'µm'
                    },
                    'Plane': {
                        'PositionX': [pos[0]*pix]*stack.shape[0],
                        'PositionY': [pos[1]*pix]*stack.shape[0]
                    }
                }
                tif.write(stack, metadata=meta)


def leica_mipping(input_dirs, output_dir_prefix, image_dimension=[2048, 2048], mode=None):
    """
    Process and MIP (maximum intensity projection) microscopy image files exported from Leica as TIFFs.

    Parameters:
    - input_dirs: List of file paths to the input directories.
    - output_dir_prefix: Prefix for the output directory.
    - image_dimension: Dimensions of the image (default is [2048, 2048]).
    """

    # Import necessary libraries
    from os import listdir
    from os.path import isfile, join
    import tifffile
    from xml.dom import minidom
    import pandas as pd
    import numpy as np
    import os
    from tifffile import imread
    from tqdm import tqdm
    import re
    import shutil


    if mode==None:
        # Refactor input directories for compatibility (especially with Linux)
        refactored_dirs = [dir_path.replace("%20", " ") for dir_path in input_dirs]
    
        # Iterate through each input directory
        for idx, dir_path in enumerate(refactored_dirs):
    
            # Get list of files in the directory
            files = os.listdir(dir_path)
            
            # Filter for TIFF files that are not deconvolved
            tif_files = [file for file in files if 'dw' not in file and '.tif' in file and '.txt' not in file]
            
            # Split filenames to get the regions
            split_underscore = pd.DataFrame(tif_files)[0].str.split('--', expand=True)
            unique_regions = list(split_underscore[0].unique())
    
            # If the scan is large, it may be divided into multiple regions
            for region in unique_regions:
                region_tif_files = [file for file in tif_files if region in file]
                base_index = str(idx + 1)
                split_underscore = pd.DataFrame(region_tif_files)[0].str.split('--', expand=True)
                
                # Extract tiles information
                tiles = sorted(split_underscore[1].unique())
                tiles_df = pd.DataFrame(tiles)
                tiles_df['indexNumber'] = [int(tile.split('e')[-1]) for tile in tiles_df[0]]
                tiles_df.sort_values(by=['indexNumber'], ascending=True, inplace=True)
                tiles_df.drop('indexNumber', axis=1, inplace=True)
                tiles = list(tiles_df[0])
                
                # Extract channels information
                channels = split_underscore[3].unique()
                
                # Determine the output directory based on the region
                if len(unique_regions) == 1:
                    output_dir = output_dir_prefix
                else:
                    output_dir = f"{output_dir_prefix}_R{region.split('Region')[1].split('_')[0]}"
                mipped_output_dir = f"{output_dir}/preprocessing/mipped/"
                
                # Create directory if it doesn't exist
                if not os.path.exists(mipped_output_dir):
                    os.makedirs(mipped_output_dir)
    
                for base_idx, base in enumerate(sorted(base_index)):
                    if not os.path.exists(f"{mipped_output_dir}/Base_{base}"):
                        os.makedirs(f"{mipped_output_dir}/Base_{base}")
                    try:
                        metadata_file = join(dir_path, 'Metadata', [file for file in os.listdir(join(dir_path, 'Metadata')) if region in file][0])
                        if not os.path.exists(join(mipped_output_dir, f"Base_{base}", 'MetaData')):
                            os.makedirs(join(mipped_output_dir, f"Base_{base}", 'MetaData'))
                        customcopy(metadata_file, join(mipped_output_dir, f"Base_{base}", 'MetaData'))
                        #shutil.copy(metadata_file, join(mipped_output_dir, f"Base_{base}", 'MetaData'))
                    except FileExistsError:
                        pass
    
                    # Maximum Intensity Projection (MIP) for each tile
                    for _tile in tqdm(range(len(tiles))):
                        tile = tiles[_tile]
                        tile_for_name = re.split('(\d+)', tile)[1]
                        existing_files = [file for file in os.listdir(f"{mipped_output_dir}/Base_{base}") if str(tile_for_name) in file]
                        
                        # Ensure that we don't overwrite existing files
                        if len(existing_files) < len(channels):
                            tile_tif_files = [file for file in region_tif_files if f"{tile}--" in file]
                            for channel_idx, channel in enumerate(sorted(list(channels))):
                                channel_tif_files = [file for file in tile_tif_files if str(channel) in file]
                                max_intensity = np.zeros(image_dimension)
                                for file in channel_tif_files:
                                    try:
                                        im_array = imread(f"{dir_path}/{file}")
                                    except:
                                        print('Image corrupted, reading black file instead.')
                                        im_array = np.zeros(image_dimension)
                                    max_intensity = np.maximum(max_intensity, im_array)
                                max_intensity = max_intensity.astype('uint16')
                                tifffile.imwrite(f"{mipped_output_dir}/Base_{base}/Base_{base}_s{tile_for_name}_{channel}", max_intensity)
    if mode=='exported':
        print ('Processing Leica files from export mode')
        # Refactor input directories for compatibility (especially with Linux)
        refactored_dirs = [dir_path.replace("%20", " ") for dir_path in input_dirs]
        #print (refactored_dirs)
    
        # Iterate through each input directory
        for idx, dir_path in enumerate(refactored_dirs):
            # Get list of files in the directory
            files = os.listdir(dir_path)
            # Filter for TIFF files that are not deconvolved
            tif_files = [file for file in files if 'dw' not in file and '.tif' in file and '.txt' not in file]
            split_underscore = pd.DataFrame(tif_files)[0].str.split('_', expand=True)
            unique_regions = list(split_underscore[0].unique())
            for region in unique_regions:
                print(region)
                region_tif_files = [file for file in tif_files if region in file]
                base_index = str(idx + 1)
                split_underscore = pd.Series(region_tif_files).str.split('_', expand=True)
                tiles = sorted(split_underscore.iloc[:, -3].unique())
                tiles_df = pd.DataFrame(tiles)
                tiles_df['indexNumber'] = [int(tile.split('s')[-1]) for tile in tiles_df[0]]
                tiles_df.sort_values(by=['indexNumber'], ascending=True, inplace=True)
                tiles_df.drop(labels='indexNumber', axis=1, inplace=True)
                tiles = list(tiles_df[0])
                channels = split_underscore.iloc[:, -1].unique()
                # Determine the output directory based on the region
                if len(unique_regions) == 1:
                    output_dir = output_dir_prefix
                else:
                    output_dir = f"{output_dir_prefix}_R{region.split('Region')[1].split('_')[0]}"
                mipped_output_dir = f"{output_dir}/preprocessing/mipped/"
                
                # Create directory if it doesn't exist
                if not os.path.exists(mipped_output_dir):
                    os.makedirs(mipped_output_dir)
    
                for base_idx, base in enumerate(sorted(base_index)):
                    if not os.path.exists(f"{mipped_output_dir}/Base_{base}"):
                        os.makedirs(f"{mipped_output_dir}/Base_{base}")
                    try:
                        metadata_file = join(dir_path, 'MetaData', [file for file in os.listdir(join(dir_path, 'MetaData')) if region in file][0])
                       
                        if not os.path.exists(join(mipped_output_dir, f"Base_{base}", 'MetaData')):
                            os.makedirs(join(mipped_output_dir, f"Base_{base}", 'MetaData'))
                        customcopy(metadata_file, join(mipped_output_dir, f"Base_{base}", 'MetaData'))
                        #shutil.copy(metadata_file, join(mipped_output_dir, f"Base_{base}", 'MetaData'))
                    except FileExistsError:
                        pass
    
                    # Maximum Intensity Projection (MIP) for each tile
                    for _tile in tqdm(range(len(tiles))):
                        tile = tiles[_tile]
                        tile_for_name = re.split('(\d+)', tile)[1]
                        existing_files = [file for file in os.listdir(f"{mipped_output_dir}/Base_{base}") if str(tile_for_name) in file]
                        
                        # Ensure that we don't overwrite existing files
                        if len(existing_files) < len(channels):
                            tile_tif_files = [file for file in region_tif_files if f"{tile}_" in file]
                            for channel_idx, channel in enumerate(sorted(list(channels))):
                                channel_tif_files = [file for file in tile_tif_files if str(channel) in file]
                                max_intensity = np.zeros(image_dimension)
                                for file in channel_tif_files:
                                    try:
                                        im_array = imread(f"{dir_path}/{file}")
                                    except:
                                        print('Image corrupted, reading black file instead.')
                                        im_array = np.zeros(image_dimension)
                                    max_intensity = np.maximum(max_intensity, im_array)
                                max_intensity = max_intensity.astype('uint16')
                                tifffile.imwrite(f"{mipped_output_dir}/Base_{base}/Base_{base}_s{tile_for_name}_{channel}", max_intensity)
    
    
                    






def leica_OME_tiff(directory_base, output_directory):
    """
    Convert Leica TIFF files to OME-TIFF format.
    
    Args:
    - directory_base: Base directory containing the TIFF files.
    - output_directory: Directory to save the converted OME-TIFF files.
    
    Returns:
    None. Writes the OME-TIFF images to the designated output directory.
    """
    
    import tifffile
    import numpy as np
    import os
    from os.path import join
    import tifffile
    import os
    from os import listdir
    import pandas as pd
    import numpy as np
    from xml.dom import minidom
    from pathlib import Path
    from tqdm import tqdm

    folders = os.listdir(directory_base)
    folders = [f for f in folders if f != ".DS_Store"]
    
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
        
    for folder in folders:
        exported_directory = join(directory_base,folder)
        onlyfiles = listdir(exported_directory)
        onlytifs =  [k for k in onlyfiles if '.tif' in k]
        onlyfiles_df = pd.DataFrame(onlytifs)
        onlyfiles_split_tiles = onlyfiles_df[0].str.split('_s',expand=True)
        onlyfiles_split_channel = onlyfiles_split_tiles[1].str.split('_',expand=True)

        tiles = list(np.unique(onlyfiles_split_tiles[1].str.split('_',expand=True)[0]))
        tiles_df=pd.DataFrame(tiles)
        tiles_df['indexNumber'] = [int(i.split('e')[-1]) for i in tiles_df[0]]
        # Perform sort of the rows
        tiles_df.sort_values(by = ['indexNumber'], ascending = [True], inplace = True)
        # Deletion of the added column
        tiles_df.drop('indexNumber', axis=1, inplace = True)
        tiles = list(tiles_df[0])
        channels = list(np.unique(onlyfiles_split_channel[1]))
        rounds = list(np.unique(onlyfiles_split_tiles[0]))
        
        
        metadatafiles = listdir(join(exported_directory, 'MetaData'))
        metadatafiles =  [k for k in metadatafiles if 'IOManagerConfiguation.xlif' not in k]

        for p, meta in enumerate(metadatafiles):
            print(meta)
            mydoc = minidom.parse(join(exported_directory, 'MetaData',meta) )
            tile =[]
            x =[]
            y =[]
            items = mydoc.getElementsByTagName('Tile')
            for el, elem in enumerate(items):
                tile.append(el)
                x.append(float(elem.attributes['PosX'].value))
                y.append(float(elem.attributes['PosY'].value))
            unique_tiles = list(np.unique(tile))
            x_reformatted = (x[:len(unique_tiles)])    
            y_reformatted = (y[:len(unique_tiles)])     
            dictionary = {'x': x_reformatted, 'y': y_reformatted}  

            df = pd.DataFrame(dictionary)
            df['x'] =((df.x-np.min(df.x))/.000000321) + 1
            df['y'] =((df.y-np.min(df.y))/.000000321) + 1
            positions = np.array(df).astype(int)
            df.to_csv(directory_base +'/'+ folder + '/coords.csv')
            
        with tifffile.TiffWriter((output_directory +'/'+ folder + '.ome.tiff'), bigtiff=True) as tif:
            for i in tqdm(range(len(tiles))):
                position = positions[i]
                tile = tiles[i]

                tile_filtered = [k for k in onlytifs if 's'+tile+'_' in k]
                tile_filtered =  [k for k in tile_filtered if '._' not in k]

                stacked = np.empty((len(channels), 2048, 2048))
                for n,image_file in enumerate(sorted(tile_filtered)):
                    try: 
                        image_int = tifffile.imread(join(exported_directory,image_file))
                    except IndexError: 
                        image_int = np.empty((2048, 2048))
                    stacked[n] = image_int.astype('uint16')
                pixel_size = 0.1625
                metadata = {
                                'Pixels': {
                                    'PhysicalSizeX': pixel_size,
                                    'PhysicalSizeXUnit': 'µm',
                                    'PhysicalSizeY': pixel_size,
                                    'PhysicalSizeYUnit': 'µm'
                                },
                                'Plane': {
                                    'PositionX': [position[0]*pixel_size]*stacked.shape[0],
                                    'PositionY': [position[1]*pixel_size]*stacked.shape[0]
                                }

                            }
                tif.write(stacked.astype('uint16'),metadata=metadata)


def ashlar_wrapper(
    files,
    output='',
    align_channel=1,
    flip_x=False,
    flip_y=True,
    output_channels=None,
    maximum_shift=500,
    filter_sigma=5.0,
    filename_format='Round{cycle}_{channel}.tif',
    pyramid=False,
    tile_size=None,
    ffp=False,
    dfp=False,
    plates=False,
    quiet=False,
    version=False
):
    """
    Wrapper for Ashlar alignment and mosaicking, with keyword-only parameter calls.
    """
    ashlar.configure_terminal()
    filepaths = files
    output_path = pathlib.Path(output)
    import warnings; warnings.filterwarnings('ignore')

    if not os.path.exists(output): os.makedirs(output)
    if tile_size and not pyramid:
        ashlar.print_error("--tile-size can only be used with --pyramid")
        return 1

    # flat/dark-field profiles
    ffp_paths = ffp
    if ffp_paths:
        if len(ffp_paths) not in (0, 1, len(filepaths)):
            ashlar.print_error(
                f"Wrong number of flat-field profiles. Must be 1, or {len(filepaths)}"
            )
            return 1
        if len(ffp_paths) == 1:
            ffp_paths = ffp_paths * len(filepaths)

    dfp_paths = dfp
    if dfp_paths:
        if len(dfp_paths) not in (0, 1, len(filepaths)):
            ashlar.print_error(
                f"Wrong number of dark-field profiles. Must be 1, or {len(filepaths)}"
            )
            return 1
        if len(dfp_paths) == 1:
            dfp_paths = dfp_paths * len(filepaths)

    aligner_args = {
        'channel': align_channel,
        'verbose': not quiet,
        'max_shift': maximum_shift,
        'filter_sigma': filter_sigma
    }
    mosaic_args = {}
    if output_channels: mosaic_args['channels'] = output_channels
    if pyramid: mosaic_args['tile_size'] = tile_size
    if not quiet: mosaic_args['verbose'] = True

    try:
        if plates:
            return ashlar.process_plates(
                filepaths=filepaths,
                output_dir=output_path,
                filename_format=filename_format,
                flip_x=flip_x,
                flip_y=flip_y,
                ffp_paths=ffp_paths,
                dfp_paths=dfp_paths,
                aligner_args=aligner_args,
                mosaic_args=mosaic_args,
                pyramid=pyramid,
                quiet=quiet
            )
        else:
            mosaic_fmt = str(output_path / filename_format)
            return ashlar.process_single(
                filepaths=filepaths,
                output_path_format=mosaic_fmt,
                flip_x=flip_x,
                flip_y=flip_y,
                ffp_paths=ffp_paths,
                dfp_paths=dfp_paths,
                barrel_correction=0,
                aligner_args=aligner_args,
                mosaic_args=mosaic_args,
                pyramid=pyramid,
                quiet=quiet
            )
    except ashlar.ProcessingError as e:
        ashlar.print_error(str(e))
        return 1


def reshape_split(image: np.ndarray, kernel_size: tuple):
    """
    Reshape the input image into smaller tiles of specified size.
    
    Args:
    - image (np.ndarray): 2D array representing the image.
    - tile_size (tuple): Desired dimensions for the tiles (height, width).
    
    Returns:
    - np.ndarray: 4D array representing tiles of the image.
    """    
    img_height, img_width = image.shape
    tile_height, tile_width = kernel_size
    
    tiled_array = image.reshape(img_height // tile_height, 
                               tile_height, 
                               img_width // tile_width, 
                               tile_width)
    
    tiled_array = tiled_array.swapaxes(1,2)
    return tiled_array

    


def tile_stitched_images(image_path,outpath, tile_dim=2000, file_type = 'tif', old_stiched_name = False):

    """
    Tiles stitched images from a directory and saves them with a specific naming convention.
    
    Args:
    - image_directory (str): Directory containing the stitched images.
    - output_directory (str): Directory to save the tiled images.
    - tile_dim (int): Dimension for tiling. Default is 2000.
    - file_type (str): Type of the image file. Default is 'tif'.
    - old_stitched_naming (bool): Flag to handle old naming convention. Default is False.
    """
    
    if not os.path.exists(outpath):
            os.makedirs(outpath)
            
    images = os.listdir(image_path)
    images =  [k for k in images if '._' not in k]
    
    if file_type=='mat':
        images =  [k for k in images if '.tif.mat' in k] 
    else: 
        images =  [k for k in images if '.tif' in k] 

    for image_file in sorted(images):
        try: 
            if file_type == 'mat':
                image = mat73.loadmat(image_path +'/'+ image_file)['I']
                cycle = ''.join(filter(str.isdigit, image_file.split('_')[1]))
                channel = ''.join(filter(str.isdigit, image_file.split('_')[2].split('-')[1].split('.')[0]))
            else:
                if old_stiched_name == True:
                    print('old names')
                    image = tifffile.imread(image_path +'/'+ image_file)
                    cycle = str(int(''.join(filter(str.isdigit, image_file.split('_')[1])))-1)
                    channel = str(int(''.join(filter(str.isdigit, image_file.split('-')[1])))-1)
                    print(cycle)
                    print(channel)
                else: 
                    image = tifffile.imread(image_path +'/'+ image_file)
                    cycle = ''.join(filter(str.isdigit, image_file.split('_')[0]))
                    channel = ''.join(filter(str.isdigit, image_file.split('_')[1]))

           
            
            print('tiling: ' + image_file)
            
            image_pad = cv2.copyMakeBorder( image, top = 0, bottom =math.ceil(image.shape[0]/tile_dim)*tile_dim-image.shape[0], left =0, right = math.ceil(image.shape[1]/tile_dim)*tile_dim-image.shape[1], borderType = cv2.BORDER_CONSTANT)
            image_split = reshape_split(image_pad,(tile_dim,tile_dim))
            nrows, ncols, dim1, dim2 = image_split.shape
            x = []
            y = []
            directory = outpath +'/'+'Base_'+str(int(cycle)+1)+'_stitched-'+str(int(channel)+1) 
            if not os.path.exists(directory):
                os.makedirs(directory) 
            count = 0
            for i in range(nrows):
                for j in range(ncols):
                    count = count+1                
                    x.append(j*tile_dim)
                    y.append(i*tile_dim)
                    
                    tifffile.imwrite(directory + '/' +'tile'+str(count)+'.tif',image_split[i][j])
        except KeyError:
            continue
                
    tile_pos = pd.DataFrame()
    tile_pos['x'] = x
    tile_pos['y'] = y

    tile_pos.to_csv(outpath+'/'+'tilepos.csv', header=False, index=False)
    return
    
    
def preprocessing_main_leica(input_dirs, 
                            output_location,
                            regions_to_process = 2, 
                            align_channel = 4, 
                            tile_dimension = 6000, 
                            mip = True,
                            mode = None):
    """
    Main function to preprocess Leica microscopy images.

    Args:
    - input_dirs (str): Directories containing input images.
    - output_location (str): Base output directory.
    - regions_to_process (int): Number of regions to process. Default is 2.
    - align_channel (int): Channel to use for alignment. Default is 4.
    - tile_dimension (int): Dimension for tiling. Default is 6000.
    - mip (bool): Flag to perform maximum intensity projection. Default is True. Use false for pre-mipped images
    """
    
    # Maximum Intensity Projection
    if mip == True:
        leica_mipping(input_dirs=input_dirs, output_dir_prefix = output_location)
    else: 
        print('not mipping')
        
    if regions_to_process > 1:
        for i in range(regions_to_process):
            path = output_location +'_R'+str(i+1)
            
            # create leica OME_tiffs
            leica_OME_tiff(directory_base = path+'/preprocessing/mipped/', 
                                            output_directory = path+'/preprocessing/OME_tiffs/',
                                            mode = mode)
            
            # align and stitch images
            OME_tiffs_dir = os.path.join(path, 'preprocessing', 'OME_tiffs')
            OME_tiffs = natsorted([
                os.path.join(OME_tiffs_dir, fname)
                for fname in os.listdir(OME_tiffs_dir)
            ])
            ashlar_wrapper(files = OME_tiffs, 
                                            output = path+'/preprocessing/stitched/', 
                                            align_channel=align_channel)
            
            # retile stitched images
            tile_stitched_images(image_path = path+'/preprocessing/stitched/',
                                    outpath = path+'/preprocessing/ReslicedTiles/', 
                                    tile_dim=tile_dimension)

    
    else: 
        path = output_location

        # create leica OME_tiffs
        leica_OME_tiff(directory_base = path+'/preprocessing/mipped/', 
                                        output_directory = path+'/preprocessing/OME_tiffs/')

        # align and stitch images
        OME_tiffs_dir = os.path.join(path, 'preprocessing', 'OME_tiffs')
        OME_tiffs = natsorted([
            os.path.join(OME_tiffs_dir, fname)
            for fname in os.listdir(OME_tiffs_dir)
        ])

        ashlar_wrapper(files = OME_tiffs, 
                                        output = path+'/preprocessing/stitched/', 
                                        align_channel=align_channel)

        # retile stitched images
        tile_stitched_images(image_path = path+'/preprocessing/stitched/',
                                outpath = path+'/preprocessing/ReslicedTiles/', 
                                tile_dim=tile_dimension)
    return






def process_czi(input_file, outpath, mip=True, cycle=0, tile_size_x=2048, tile_size_y=2048):
    """
    Process CZI files, apply maximum intensity projection (if specified), 
    and create an associated XML with metadata.
    
    Parameters:
    - input_file: Path to the input CZI file.
    - outpath: Directory where the processed images and XML will be saved.
    - mip: Boolean to decide whether to apply maximum intensity projection. Default is True.
    - cycle: Int to specify the cycle number. Default is 0.
    - tile_size_x: Size of the tile in X dimension. Default is 2048.
    - tile_size_y: Size of the tile in Y dimension. Default is 2048.
    
    Returns:
    - A string indicating that processing is complete.
    """
    
    # import packages 
    import os
    import xml.etree.ElementTree as ET
    from aicspylibczi import CziFile
    import aicspylibczi
    from xml.dom import minidom
    import numpy as np
    from tqdm import tqdm
    import pandas as pd
    import tifffile
    
    # Create the output directory if it doesn't exist.
    if not os.path.exists(outpath):
        os.makedirs(outpath)


    # Load the CZI file and retrieve its dimensions.
    czi = aicspylibczi.CziFile(input_file)
    dimensions = czi.get_dims_shape() 
    chsize = dimensions[0]['C'][1]
    try:
        msize=dimensions[0]['M'][1]
    except:
        msize=0 
    ssize = dimensions[0]['S'][1]

    # Check if mip is True and cycle is not zero.
    if mip and cycle != 0:
        # Initialize placeholders for metadata.
        Bxcoord = []
        Bycoord = []
        Btile_index = []
        filenamesxml = []
        Bchindex = []

        # Loop through each mosaic tile and each channel.
        for m in tqdm(range(0, msize)):
            for ch in range (0, chsize):
                # Get metadata and image data for the current tile and channel.
                meta = czi.get_mosaic_tile_bounding_box(M=m, Z=0, C=ch)
                img, shp = czi.read_image(M=m, C=ch)
                
                # Apply maximum intensity projection.
                IM_MAX = np.max(img, axis=3)
                IM_MAX = np.squeeze(IM_MAX, axis=(0,1,2,3))
                
                # Construct filename for the processed image.
                n = str(0)+str(m+1) if m < 9 else str(m+1)
                filename = 'Base_' + str(cycle) + '_c' + str(ch+1) + 'm' + str(n) + '_ORG.tif'
                
                # Save the processed image.
                
                tifffile.imwrite(outpath + filename, IM_MAX.astype('uint16'))
                
                # Append metadata to the placeholders.
                Bchindex.append(ch)
                Bxcoord.append(meta.x)
                Bycoord.append(meta.y)
                Btile_index.append(m)
                filenamesxml.append(filename)

        # Adjust the XY coordinates to be relative.
        nBxcord = [x - min(Bxcoord) for x in Bxcoord]
        nBycord = [y - min(Bycoord) for y in Bycoord]
        
        # Create a DataFrame to organize the collected metadata.
        metadatalist = pd.DataFrame({
            'Btile_index': Btile_index, 
            'Bxcoord': nBxcord, 
            'Bycoord': nBycord, 
            'filenamesxml': filenamesxml,
            'channelindex': Bchindex
        })
        
        metadatalist = metadatalist.sort_values(by=['channelindex','Btile_index'])
        metadatalist.reset_index(drop=True)

        # Initialize the XML document structure.
        export_doc = ET.Element('ExportDocument')
        
        # Populate the XML document with metadata.
        for index, row in metadatalist.iterrows():
            image_elem = ET.SubElement(export_doc, 'Image')
            filename_elem = ET.SubElement(image_elem, 'Filename')
            filename_elem.text = row['filenamesxml']
            
            bounds_elem = ET.SubElement(image_elem, 'Bounds')
            bounds_elem.set('StartX', str(row['Bxcoord']))
            bounds_elem.set('SizeX', str(tile_size_x))
            bounds_elem.set('StartY', str(row['Bycoord']))
            bounds_elem.set('SizeY', str(tile_size_y))
            bounds_elem.set('StartZ', '0')
            bounds_elem.set('StartC', '0')
            bounds_elem.set('StartM', str(row['Btile_index']))
            
            zoom_elem = ET.SubElement(image_elem, 'Zoom')
            zoom_elem.text = '1'

        
        # Save the constructed XML document to a file.
        xml_str = ET.tostring(export_doc)
        with open(outpath + 'Base_' + str(cycle) + '_info.xml', 'wb') as f:
            f.write(xml_str)

    return "Processing complete."

def max_project_z(image, m, c):
    # Initialize a list to hold all Z-plane data
    z_planes = []

    # Iterate over all Z-planes for the given timepoint and channel
    for z_frame in image.get_iter_z(m=m, c=c):
        # Convert the Pillow Image to a NumPy array
        z_data = np.array(z_frame)
        #print (z_data.shape)
        z_planes.append(z_data)

    # Stack all Z-planes along a new axis
    z_stack = np.stack(z_planes, axis=0)
    #print (z_stack.shape)

    # Perform maximum intensity projection along the Z-axis (axis=0)
    max_projection = np.max(z_stack, axis=0)

    return max_projection

def lif_mipping(lif_path, output_folder, cycle):
    file = LifFile(lif_path)
    
    os.makedirs(output_folder, exist_ok=True)
    if len(file.image_list) > 1:
        for index, image_dict in enumerate(file.image_list):
            image_name = image_dict['name']
            print (image_name)
            mosaic=image_dict.get('mosaic_position', None)
            #print (mosaic)
            
            # Build XML structure
            data = ET.Element("Data")
            image = ET.SubElement(data, "Image", TextDescription="")
            attachment = ET.SubElement(image, "Attachment", Name="TileScanInfo", Application="LAS AF", FlipX="0", FlipY="0", SwapXY="0")

            for x, y, pos_x, pos_y in mosaic:
                ET.SubElement(attachment, "Tile", FieldX=str(x), FieldY=str(y),
                              PosX=f"{pos_x:.10f}", PosY=f"{pos_y:.10f}")

            # Create tree and write to file
            tree = ET.ElementTree(data)

            regionID=index+1
            output_region=f'_R{regionID}'
            output_subfolder=os.path.join(output_folder, output_region)
            mipped_subfolder = f"{output_subfolder}/preprocessing/mipped/Base_{cycle}"
            os.makedirs(mipped_subfolder, exist_ok=True)
            os.makedirs(mipped_subfolder+'/MetaData', exist_ok=True)
            print(f"Extracting metadata for: {image_name}")
            image_name = image_name.replace('/', '_')
            tree.write(f"{mipped_subfolder}/MetaData/{image_name}.xml", encoding="utf-8", xml_declaration=True)
            print(f"Processing Image {index}: {image_name}")
            image = file.get_image(index)
            channels = image_dict['channels']
            dims = image_dict['dims']

            if dims.m == 1:
                print("Single tile imaging.")
                for c in range(channels):  # Loop through each channel
                    max_projected = max_project_z(image, c)  # (y, x)
                    # Clean filename
                    clean_name = f"Base_{cycle}"
                    filename = f"{clean_name}_s00_C0{c}.tif"
                    output_path = os.path.join(mipped_subfolder, filename)

                    tifffile.imwrite(output_path, max_projected.astype(np.uint16))
                    print(f"Saved: {output_path}")

            else:
                for m in range(dims.m):  # Loop through each tile
                    for c in range(channels):  # Loop through each channel
                        max_projected = max_project_z(image,m, c)  # (y, x)
                        # Clean filename
                        clean_name = f"Base_{cycle}"
                        filename = f"{clean_name}_s{m:02d}_C0{c}.tif"
                        output_path = os.path.join(mipped_subfolder, filename)

                        tifffile.imwrite(output_path, max_projected.astype(np.uint16))
                        print(f"Saved: {output_path}")
    else:
        mipped_subfolder = f"{output_folder}/preprocessing/mipped/Base_{cycle}"
        os.makedirs(mipped_subfolder, exist_ok=True)
        os.makedirs(mipped_subfolder+'/MetaData', exist_ok=True)

        for index, image_dict in enumerate(file.image_list):
            image_name = image_dict['name']
            mosaic=image_dict.get('mosaic_position', None)
            #print (mosaic)
            
            # Build XML structure
            data = ET.Element("Data")
            image = ET.SubElement(data, "Image", TextDescription="")
            attachment = ET.SubElement(image, "Attachment", Name="TileScanInfo", Application="LAS AF", FlipX="0", FlipY="0", SwapXY="0")

            for x, y, pos_x, pos_y in mosaic:
                ET.SubElement(attachment, "Tile", FieldX=str(x), FieldY=str(y),
                              PosX=f"{pos_x:.10f}", PosY=f"{pos_y:.10f}")

            # Create tree and write to file
            tree = ET.ElementTree(data)
            print(f"Extracting metadata for: {image_name}")
            tree.write(f"{mipped_subfolder}/MetaData/{image_name}.xml", encoding="utf-8", xml_declaration=True)
            
            print(f"Processing Image {index}: {image_name}")
            image = file.get_image(index)
            channels = image_dict['channels']
            dims = image_dict['dims']

            if dims.m == 1:
                print("Single tile imaging.")
                for c in range(channels):  # Loop through each channel
                    max_projected = max_project_z(image, c)  # (y, x)
                    # Clean filename
                    clean_name = f"Base_{cycle}"
                    filename = f"{clean_name}_s00_C0{c}.tif"
                    output_path = os.path.join(mipped_subfolder, filename)

                    tifffile.imwrite(output_path, max_projected.astype(np.uint16))
                    print(f"Saved: {output_path}")

            else:
                for m in range(dims.m):  # Loop through each tile
                    for c in range(channels):  # Loop through each channel
                        max_projected = max_project_z(image,m, c)  # (y, x)
                        # Clean filename
                        clean_name = f"Base_{cycle}"
                        filename = f"{clean_name}_s{m:02d}_C0{c}.tif"
                        output_path = os.path.join(mipped_subfolder, filename)

                        tifffile.imwrite(output_path, max_projected.astype(np.uint16))
                        print(f"Saved: {output_path}")

'''
This function has been developed around a dataset that is not representative of the typical nd2 format
Tiles should be in the 'm' loop while in this case they are in the 'p' loop which I think it is for positions of
single FOVs.

def process_nd2(input_file, outpath, mip=True, cycle=0):
    """
    Process nd2 files, apply maximum intensity projection (if specified), 
    and create an associated XML with metadata.
    
    Parameters:
    - input_file: Path to the input nd2 file.
    - outpath: Directory where the processed images and XML will be saved.
    - mip: Boolean to decide whether to apply maximum intensity projection. Default is True.
    - cycle: Int to specify the cycle number. Default is 0.
    
    Returns:
    - A string indicating that processing is complete.
    """
    
    # import packages 
    import os
    import pandas as pd
    import re

    import xml.etree.ElementTree as ET
    import nd2
    from xml.dom import minidom
    import numpy as np
    from tqdm import tqdm
    import pandas as pd
    import tifffile
    
    # Create the output directory if it doesn't exist.
    if not os.path.exists(outpath):
        os.makedirs(outpath)


    # Load the nd2 into array and retrieve its dimensions.
    big_file = nd2.imread(input_file)
     
    chsize = big_file.shape[2]
    msize=big_file.shape[0]
    ndfile = nd2.ND2File(input_file)
   

    # Check if mip is True and cycle is not zero.
    if mip and cycle != 0:
        # Initialize placeholders for metadata.
        Bxcoord = []
        Bycoord = []
        Btile_index = []
        filenamesxml = []
        Bchindex = []
        data_str=str(ndfile.experiment)
        ndfile.close()
        split_data = data_str.split('points=', 1)
        positions_str = split_data[1]

        # Remove the '])' from the end of the positions string
        positions_str = positions_str[:-2]

        # Split the positions string at each 'Position('
        positions_list = positions_str.split('Position(')[1:]

        # Initialize an empty list to store the Position() lines
        positions_lines = []

        # Iterate through the positions list and extract each line
        for position in positions_list:
            # Remove the trailing ')' from the line
            position_line = position.split(')')[0]
            # Append the position line to the positions_lines list
            positions_lines.append('Position(' + position_line + ')')

        # Initialize an empty list to store the extracted coordinates
        coordinates = []

        # Iterate through each line of Position() and extract x and y coordinates
        for line in positions_lines:
            # Use regular expressions to extract x and y coordinates
            match = re.search(r'x=([-+]?\d*\.\d+|\d+), y=([-+]?\d*\.\d+|\d+)', line)
            if match:
                x = float(match.group(1))
                y = float(match.group(2))
                coordinates.append({'x': x, 'y': y})

        # Create a DataFrame from the extracted coordinates
        df_coord = pd.DataFrame(coordinates)

        # Loop through each mosaic tile and each channel.
        for m in tqdm(range(0, msize)):
            for ch in range (0, chsize):
                # Get metadata and image data for the current tile and channel.
                #meta = czi.get_mosaic_tile_bounding_box(M=m, Z=0, C=ch)
                IM_MAX = np.max(big_file[m, :, ch, :, :], axis=0)
                
                # Construct filename for the processed image.
                n = str(0)+str(m+1) if m < 9 else str(m+1)
                filename = 'Base_' + str(cycle) + '_c' + str(ch+1) + 'm' + str(n) + '_ORG.tif'
                
                # Save the processed image.
                
                tifffile.imwrite(outpath + filename, IM_MAX.astype('uint16'))
                
                # Append metadata to the placeholders.
                Bchindex.append(ch)
                Bxcoord.append(df_coord.loc[m][0])
                Bycoord.append(df_coord.loc[m][1])
                Btile_index.append(m)
                filenamesxml.append(filename)

        # Adjust the XY coordinates to be relative.
        nBxcord = [x - min(Bxcoord) for x in Bxcoord]
        nBycord = [y - min(Bycoord) for y in Bycoord]
        
        # Create a DataFrame to organize the collected metadata.
        metadatalist = pd.DataFrame({
            'Btile_index': Btile_index, 
            'Bxcoord': nBxcord, 
            'Bycoord': nBycord, 
            'filenamesxml': filenamesxml,
            'channelindex': Bchindex
        })
        
        metadatalist = metadatalist.sort_values(by=['channelindex','Btile_index'])
        metadatalist.reset_index(drop=True)

        # Initialize the XML document structure.
        export_doc = ET.Element('ExportDocument')
        
        # Populate the XML document with metadata.
        for index, row in metadatalist.iterrows():
            image_elem = ET.SubElement(export_doc, 'Image')
            filename_elem = ET.SubElement(image_elem, 'Filename')
            filename_elem.text = row['filenamesxml']
            
            bounds_elem = ET.SubElement(image_elem, 'Bounds')
            bounds_elem.set('StartX', str(row['Bxcoord']))
            bounds_elem.set('SizeX', str(big_file.shape[3]))
            bounds_elem.set('StartY', str(row['Bycoord']))
            bounds_elem.set('SizeY', str(big_file.shape[4]))
            bounds_elem.set('StartZ', '0')
            bounds_elem.set('StartC', '0')
            bounds_elem.set('StartM', str(row['Btile_index']))
            
            zoom_elem = ET.SubElement(image_elem, 'Zoom')
            zoom_elem.text = '1'

        
        # Save the constructed XML document to a file.
        xml_str = ET.tostring(export_doc)
        with open(outpath + 'Base_' + str(cycle) + '_info.xml', 'wb') as f:
            f.write(xml_str)

    return "Processing complete."

'''



'''
This function is actually OK, but it's useless if the mipping and dv functions don't do the right job.
To be restored when things are properly tested

def nd2_OME_tiff(exported_directory, output_directory, channel_split=2, cycle_split=1, num_channels=5):
    """
    This function makes OME-TIFF files from files exported from as tiff from .nd2, through the process_nd2 or to the deconvolve_nd2 functions.
    
    Note: This function assumes that you are using the Nilsson SOP for naming files. It will work on 1-tile sections.
    Args:
    - exported_directory: directory containing exported TIFF files.
    - output_directory: directory to save the processed files.
    - channel_split, cycle_split: indices for splitting filenames.
    - num_channels: number of channels in the images.
    
    Returns:
    - None. Writes processed images to output_directory.
   """

    # Create the output directory if it doesn't exist
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    # Filter out TIFF files from the directory
    all_files = os.listdir(exported_directory)
    tiff_files = [file for file in all_files if '.tif' in file]

    # Split the filenames to extract tiles, channels, and rounds
    split_tiles_df = pd.DataFrame(tiff_files)[0].str.split('m', expand=True)
    split_channels_df = split_tiles_df[0].str.split('_', expand=True)
    tiles = list(np.unique(split_tiles_df[1]))
    channels = list(np.unique(split_channels_df[channel_split]))
    rounds = list(np.unique(split_channels_df[cycle_split]))

    # Iterate through rounds to process files
    for _, round_number in enumerate(rounds):
        tiff_files_round = [file for file in tiff_files if f'Base_{round_number}_' in file]
        metadata_files = [file for file in all_files if 'info.xml' in file]
        metadata_files_round = [file for file in metadata_files if f'_{round_number}_' in file]

        # Parse metadata XML files to extract tile positions
        for metadata_file in metadata_files_round:
            xml_doc = minidom.parse(os.path.join(exported_directory, metadata_file))
            tiles_xml, x_coords, y_coords = [], [], []
            bounds_elements = xml_doc.getElementsByTagName('Bounds')
            for elem in bounds_elements:
                tiles_xml.append(int(elem.attributes['StartM'].value))
                x_coords.append(float(elem.attributes['StartX'].value))
                y_coords.append(float(elem.attributes['StartY'].value))
                
            unique_tiles_xml = list(np.unique(tiles_xml))
            position_df = pd.DataFrame({
                'x': x_coords[:len(unique_tiles_xml)],
                'y': y_coords[:len(unique_tiles_xml)]
            })
            positions = np.array(position_df).astype(int)

        # Write processed images to OME-TIFF format
        with tifffile.TiffWriter(os.path.join(output_directory, f'cycle_{round_number}.ome.tif'), bigtiff=True) as tif:
            for i in tqdm(range(len(tiles))):
                position = positions[i]
                tile = tiles[i]
                tiff_files_tile = [file for file in tiff_files_round if f'm{tile}' in file and '._' not in file]
                stacked_images = np.empty((num_channels, 2048, 2048))

                for idx, image_file in enumerate(sorted(tiff_files_tile)):
                    image_data = tifffile.imread(os.path.join(exported_directory, image_file))
                    stacked_images[idx] = image_data.astype('uint16')

                pixel_size = 0.1625
                metadata = {
                    'Pixels': {
                        'PhysicalSizeX': pixel_size,
                        'PhysicalSizeXUnit': 'µm',
                        'PhysicalSizeY': pixel_size,
                        'PhysicalSizeYUnit': 'µm'
                    },
                    'Plane': {
                        'PositionX': [position[0] * pixel_size] * stacked_images.shape[0],
                        'PositionY': [position[1] * pixel_size] * stacked_images.shape[0]
                    }
                }
                tif.write(stacked_images.astype('uint16'), metadata=metadata)
'''

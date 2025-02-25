import zipfile
import base64
import os, io

def dir_to_str(directory_path: str) -> str:
    """
    Compresses a directory into a base64 encoded string using zipfile. 
    
    Args:
        directory_path (str): Path to the directory to compress. 
    
    Returns: 
        str: Base64 encoded string representing the compressed directory. 
    """
    with io.BytesIO() as f:
        with zipfile.ZipFile(f, 'w', compression=zipfile.ZIP_DEFLATED) as zip_file:
            for root, _, files in os.walk(directory_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    #print(os.path.relpath(file_path, directory_path))
                    zip_file.write(file_path, arcname=os.path.relpath(file_path, directory_path))
        f.seek(0)
        compressed_data = f.read()
    return base64.b64encode(compressed_data).decode('utf-8')

def str_to_dir(compressed_string: str, target_directory: str) -> None:
    """
    Decompresses a base64 encoded string and extracts files to a target directory. 
    
    Args:
        compressed_string (str): Base64 encoded string representing a compressed directory.
        target_directory (str): Path to the directory where files will be extracted. 
    """
    decoded_data = base64.b64decode(compressed_string)
    with zipfile.ZipFile(io.BytesIO(decoded_data), 'r') as zip_file:
        zip_file.extractall(target_directory) 

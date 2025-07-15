import os
import subprocess
import sys
import multiprocessing
import argparse
import shutil
import getpass
import concurrent.futures
from tqdm import tqdm
from datetime import datetime
import re
import logging

# Constants
FLAC_EXTENSION = ".flac"
TEMP_EXTENSION = ".tmp"
LOG_FILENAME = "flacr_error.log"
MIN_FLAC_VERSION = (1, 5, 0)
DEFAULT_PADDING = 4096
MIN_RSGAIN_THREADS = 2


def safe_print(text):
    """
    Print text safely, handling Unicode encoding errors by replacing problematic characters.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        # Replace Unicode characters that can't be encoded in the console's encoding
        safe_text = text.encode('ascii', 'replace').decode('ascii')
        print(safe_text)


def validate_dependencies(check_encoder=False, calc_rsgain=False):
    """
    Validate that all required dependencies are available.
    Returns a list of missing dependencies.
    """
    missing = []
    
    if not shutil.which("flac"):
        missing.append("flac")
    
    if check_encoder and not shutil.which("metaflac"):
        missing.append("metaflac")
    
    if calc_rsgain and not shutil.which("rsgain"):
        missing.append("rsgain")
    
    return missing


def parse_arguments():
    def dir_path(path):
        if os.path.isdir(path) and path != None:
            return path
        else:
            raise argparse.ArgumentTypeError(f"readable_dir:{path} is not a valid path")

    class thread_count:
        def __init__(self, string):
            self._val = int(string)
            max_threads = multiprocessing.cpu_count()
            if not 0 < self._val <= max_threads:
                raise argparse.ArgumentTypeError(
                    f"Invalid thread count, supply a value between 1 and {max_threads}"
                )

        def __int__(self):
            return self._val

    parser = argparse.ArgumentParser(
        description="Scan for .flac files in subdirectories, recompress them and optionally calculate replay gain tags."
    )
    parser.add_argument(
        "-d",
        "--directory",
        help="The directory that will be recursively scanned for .flac files.",
        type=dir_path,
        default=".",
        const=".",
        nargs="?",
    )
    parser.add_argument(
        "-j",
        action="store_true",
        help="flac >=1.5.0: Encode 1 file at a time with multi-threading (threadcount specified via -m) instead of encoding multiple files concurrently.",
    )
    parser.add_argument(
        "-l",
        "--log",
        action="count",
        help="Log errors during recompression or testing to flacr.log.",
    )
    parser.add_argument(
        "-m",
        "--multi_threaded",
        type=thread_count,
        default=1,
        const=1,
        nargs="?",
        help="The number of threads used during conversion and replay gain calculation, default: 1.",
    )
    parser.add_argument(
        "-p",
        "--progress",
        action="store_true",
        help='Show progress bars during scanning/recompression/testing. Useful for huge directories. Requires tqdm, use "pip3 install tqdm" to install it.',
    )
    parser.add_argument(
        "-r",
        "--rsgain",
        action="store_true",
        help="Calculate replay gain values with rsgain and save them in the audio file tags.",
    )
    parser.add_argument(
        "-s",
        "--single_folder",
        action="store_true",
        help="Only scan the current folder for flac files to recompress, no subdirectories.",
    )
    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        help="Skip recompression and only log decoding errors to console or log when used with -l.",
    )
    parser.add_argument(
        "-Q",
        "--quick",
        action="store_true",
        help="Equal to using -m with the max available threadcount, -r to calculate replay gain values and -p to display a progress bar.",
    )
    parser.add_argument(
        "-S",
        "--sequential",
        action="store_true",
        help="Equal to using -m 4 -j to encode 1 file at a time with 4 threads, -r to calculate replay gain values and -p to display a progress bar.",
    )
    parser.add_argument(
        "-E",
        "--check-encoder",
        action="store_true",
        help="Check and fix ENCODER metadata tags. Ensures each file has a single ENCODER tag matching the vendor string from the file's STREAMINFO.",
    )

    args: argparse.Namespace = parser.parse_args()

    if args.quick or args.sequential:
        setattr(args, "rsgain", True)
        setattr(args, "progress", True)
    if args.quick:
        setattr(args, "multi_threaded", multiprocessing.cpu_count())
    if args.sequential:
        setattr(
            args,
            "multi_threaded",
            (4 if 4 <= multiprocessing.cpu_count() else multiprocessing.cpu_count()),
        )
        setattr(args, "j", True)

    return args


def find_flac_files(directory, single_folder, progress):
    """
    Find all FLAC files in the specified directory.
    
    Args:
        directory: Directory to search
        single_folder: If True, only search current folder, not subdirectories
        progress: Whether to show progress bar
    
    Returns:
        List of absolute paths to FLAC files
    """
    flac_files = []
    
    try:
        safe_print(f"Scanning for FLAC files in: {directory}")
        if not single_folder:
            safe_print("Scanning subdirectories recursively...")
            with tqdm(
                desc="scanning", unit=" files", disable=not progress, ncols=100
            ) as pbar:
                flac_count = 0
                for root, dirs, files in os.walk(directory):
                    # Show current directory being scanned
                    if root != directory:
                        rel_path = os.path.relpath(root, directory)
                        pbar.set_postfix({"dir": rel_path[:30] + "..." if len(rel_path) > 30 else rel_path})
                    
                    for file in files:
                        pbar.update(1)
                        if file.lower().endswith(FLAC_EXTENSION):
                            full_path = os.path.join(os.path.abspath(root), file)
                            flac_files.append(full_path)
                            flac_count += 1
                            pbar.set_postfix({"flac files found": flac_count})
                            # Occasional output for GUI
                            if flac_count % 50 == 0:
                                safe_print(f"Found {flac_count} FLAC files so far...")
        else:
            safe_print("Scanning current folder only...")
            with tqdm(
                desc="scanning", unit=" files", disable=not progress, ncols=100
            ) as pbar:
                flac_count = 0
                try:
                    files = os.listdir(directory)
                    for file in files:
                        pbar.update(1)
                        if file.lower().endswith(FLAC_EXTENSION):
                            file_path = os.path.join(os.path.abspath(directory), file)
                            if os.path.isfile(file_path):  # Ensure it's actually a file
                                flac_files.append(file_path)
                                flac_count += 1
                                pbar.set_postfix({"flac files found": flac_count})
                except OSError as e:
                    safe_print(f"Error listing directory contents: {e}")
                    return []
    except PermissionError as e:
        safe_print(f"Permission denied accessing directory {directory}: {e}")
        return []
    except Exception as e:
        safe_print(f"Error scanning directory {directory}: {e}")
        return []
    
    return flac_files


def verify_flac(file_path):
    # Define the verify command
    command = ["flac", "-t", "--silent", file_path]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=600  # 10 minute timeout for verification
        )
        return file_path, result.stderr
    except subprocess.TimeoutExpired:
        return file_path, f"Verification timeout (10 minutes exceeded) for file: {file_path}"
    except subprocess.CalledProcessError as e:
        return file_path, e.stderr
    except Exception as e:
        return file_path, f"Unexpected error during verification: {e}"


def get_system_flac_version():
    """
    Returns the version tuple (major, minor, patch) of the local flac binary, or None if not found.
    """
    try:
        result = subprocess.run(
            ["flac", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        # Example output: "flac 1.5.0" or "flac 1.5.0 20250211"
        m = re.search(r"flac (\d+)\.(\d+)\.(\d+)", result.stdout)
        if m:
            return tuple(map(int, m.groups()))
    except Exception:
        pass
    return None


def get_flac_encoder_string():
    """
    Returns the encoder string, e.g. 'reference libFLAC 1.5.0', from the local flac binary.
    """
    try:
        result = subprocess.run(
            ["flac", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        # Example output: "flac 1.5.0" or "flac 1.5.0 20250211"
        # First try to match version with optional date
        m = re.search(r"flac (\d+\.\d+\.\d+)(?:\s+(\d+))?", result.stdout)
        if m:
            version = m.group(1)
            date = m.group(2)
            if date:
                return f"reference libFLAC {version} {date}"
            else:
                return f"reference libFLAC {version}"
    except Exception:
        pass
    return "reference libFLAC"


def get_file_flac_version(file_path):
    """
    Returns the version tuple (major, minor, patch) of the FLAC encoder used to encode the file, or None if not found.
    Checks the vendor string from the VORBIS_COMMENT block using metaflac.
    """
    try:
        result = subprocess.run(
            ["metaflac", "--show-vendor-tag", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=30  # 30 second timeout for metadata reading
        )
        # Example output: "reference libFLAC 1.4.2 20221022"
        match = re.search(r"libFLAC (\d+)\.(\d+)\.(\d+)", result.stdout)
        if match:
            return tuple(map(int, match.groups()))
        return None
    except subprocess.TimeoutExpired:
        safe_print(f"Timeout reading metadata from {file_path}")
        return None
    except Exception:
        return None


def get_file_encoder_string(file_path):
    """
    Returns the full encoder string from the vendor tag, or None if not found.
    Example: "reference libFLAC 1.4.2 20221022"
    """
    try:
        result = subprocess.run(
            ["metaflac", "--show-vendor-tag", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=30  # 30 second timeout for metadata reading
        )
        return result.stdout.strip() if result.stdout.strip() else None
    except subprocess.TimeoutExpired:
        safe_print(f"Timeout reading encoder string from {file_path}")
        return None
    except Exception:
        return None


def get_encoder_metadata_tags(file_path):
    """
    Returns a list of ENCODER metadata tag values from the file, or empty list if none found.
    """
    try:
        result = subprocess.run(
            ["metaflac", "--show-tag=ENCODER", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        # Output format: "ENCODER=reference libFLAC 1.5.0" (one per line if multiple)
        encoder_tags = []
        for line in result.stdout.strip().split('\n'):
            if line.startswith('ENCODER='):
                encoder_tags.append(line[8:])  # Remove "ENCODER=" prefix
        return encoder_tags
    except Exception:
        return []


def check_and_fix_encoder_metadata(file_path, fix_issues=True):
    """
    Checks if the ENCODER metadata field is properly filled and fixes issues if requested.
    Returns a tuple (needs_fix, issues_found, fixed) where:
    - needs_fix: True if the file had encoder metadata issues
    - issues_found: list of issues found
    - fixed: True if issues were successfully fixed
    """
    issues_found = []
    fixed = False
    
    # Get current ENCODER tags
    encoder_tags = get_encoder_metadata_tags(file_path)
    
    # Get the actual encoder string from vendor tag
    file_encoder_string = get_file_encoder_string(file_path)
    
    if not file_encoder_string:
        issues_found.append("No vendor tag found in file")
        return True, issues_found, False
    
    # Check for missing ENCODER tag
    if not encoder_tags:
        issues_found.append("Missing ENCODER metadata tag")
    
    # Check for duplicate ENCODER tags
    elif len(encoder_tags) > 1:
        issues_found.append(f"Duplicate ENCODER tags found: {len(encoder_tags)} entries")
    
    # Check if ENCODER tag matches the vendor string
    elif len(encoder_tags) == 1:
        current_encoder = encoder_tags[0]
        if current_encoder != file_encoder_string:
            if current_encoder == "reference libFLAC":
                issues_found.append("ENCODER tag missing version information")
            else:
                issues_found.append(f"ENCODER tag mismatch: '{current_encoder}' vs vendor '{file_encoder_string}'")
    
    # Fix issues if requested
    if issues_found and fix_issues:
        try:
            # Remove all existing ENCODER tags first
            if encoder_tags:
                subprocess.run(
                    ["metaflac", "--remove-tag=ENCODER", file_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    check=True,
                )
            
            # Set the correct ENCODER tag based on vendor string
            subprocess.run(
                ["metaflac", f"--set-tag=ENCODER={file_encoder_string}", file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            fixed = True
        except Exception as e:
            issues_found.append(f"Failed to fix ENCODER metadata: {e}")
    
    needs_fix = len(issues_found) > 0
    return needs_fix, issues_found, fixed


def is_flac_1_5_or_newer(file_path):
    """
    Returns True if the FLAC file was encoded with FLAC 1.5.0 or newer, else False.
    Also checks if the file's encoder version matches the system's flac version.
    """
    try:
        file_version = get_file_flac_version(file_path)
        if file_version is None:
            # If we can't determine the version, assume it needs re-encoding
            safe_print(f"Cannot determine FLAC version for {file_path}, will re-encode.")
            return False
        
        major, minor, patch = file_version
        is_new_enough = (major > 1) or (major == 1 and minor >= 5)
        
        if is_new_enough:
            # Check if file version matches system version
            system_version = get_system_flac_version()
            if system_version is not None:
                if file_version == system_version:
                    return True
                else:
                    # File was encoded with a different version, consider re-encoding
                    safe_print(f"File {file_path} was encoded with libFLAC {'.'.join(map(str, file_version))}, "
                              f"but system has libFLAC {'.'.join(map(str, system_version))}. Will re-encode for consistency.")
                    return False
        
        return is_new_enough
    except Exception as e:
        safe_print(f"Error checking FLAC version for {file_path}: {e}. Will re-encode.")
        return False


def reencode_flac(file_path, thread_count=1):
    """
    Re-encode a FLAC file with optimal settings.
    
    Args:
        file_path: Path to the FLAC file
        thread_count: Number of threads to use for encoding
    
    Returns:
        Tuple of (file_path, error_message)
    """
    # Define the temporary output file path
    temp_file_path = file_path + TEMP_EXTENSION

    # Define the re-encoding command
    command = ["flac", "--best", "--verify", f"--padding={DEFAULT_PADDING}", "--silent"]

    if thread_count > 1:
        command.append(f"--threads={thread_count}")

    command.extend([file_path, "-o", temp_file_path])

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            timeout=3600  # 1 hour timeout for safety
        )
        
        if result.stderr:
            safe_print(f"Error encountered while re-encoding {file_path}:\n{result.stderr}")
            # Clean up temp file on error
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass
            return file_path, result.stderr
        else:
            # Replace the original file with the temporary file
            try:
                # Verify temp file exists and has content
                if not os.path.exists(temp_file_path) or os.path.getsize(temp_file_path) == 0:
                    return file_path, "Temporary file is missing or empty"
                
                # Create backup of original file permissions
                original_stat = os.stat(file_path)
                
                os.remove(file_path)
                os.rename(temp_file_path, file_path)
                
                # Restore original permissions
                os.chmod(file_path, original_stat.st_mode)
                
                # Remove any existing ENCODER tags first, then set the new one
                subprocess.run(
                    ["metaflac", "--remove-tag=ENCODER", file_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                # Set ENCODER tag
                encoder_str = get_flac_encoder_string()
                subprocess.run(
                    ["metaflac", f"--set-tag=ENCODER={encoder_str}", file_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except PermissionError:
                return file_path, f"File locked. Manual replacement required. Temporary file: {temp_file_path}"
            except OSError as e:
                return file_path, f"File system error: {e}. Temporary file: {temp_file_path}"
                
        return file_path, ""
        
    except subprocess.TimeoutExpired:
        # Clean up on timeout
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
        return file_path, "Encoding timeout (1 hour limit exceeded)"
    except subprocess.CalledProcessError as e:
        # Clean up on process error
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
        return file_path, e.stderr
    except Exception as e:
        # Clean up on unexpected error
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
        return file_path, f"Unexpected error: {e}"


def run_rsgain(directory, thread_count):
    """
    Calculate replay gain values using rsgain.
    
    Args:
        directory: Directory to process
        thread_count: Number of threads to use
    """
    # Set rsgain thread count to at least 2 to prevent windows cli limitations
    if thread_count == 1:
        thread_count = MIN_RSGAIN_THREADS
    
    safe_print(f"Starting replay gain calculation with {thread_count} threads...")
    safe_print(f"Scanning directory: {directory}")
    
    # Define the replay gain calculation command
    rs_gain_command = ["rsgain", "easy", "-m", str(thread_count), directory]
    
    try:
        # Start process and show real-time output
        process = subprocess.Popen(
            rs_gain_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Read output line by line to provide feedback
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                # Forward rsgain output with prefix for GUI recognition
                safe_print(f"rsgain: {line.rstrip()}")
        
        # Wait for completion
        process.wait()
        
        if process.returncode == 0:
            safe_print("Replay gain calculation completed successfully.")
        else:
            safe_print(f"rsgain exited with code {process.returncode}")
            
    except subprocess.TimeoutExpired:
        safe_print("rsgain calculation timed out (2 hour limit)")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        safe_print(f"Error while executing rsgain: {e}")
        if hasattr(e, 'stderr') and e.stderr:
            safe_print(f"rsgain stderr: {e.stderr}")
        sys.exit(1)
    except Exception as e:
        safe_print(f"Unexpected error running rsgain: {e}")
        sys.exit(1)


def write_log(error_log):
    if not os.access(".", os.W_OK | os.X_OK):
        print(
            "Cannot write log file to current directory. Ensure that you have write permission. Skipping log creation."
        )
        return
    if len(error_log) > 0:
        with open(f"flacr_error.log", "a", encoding="utf8") as log:
            now = datetime.now()
            log.write(f'\nflacr error log, date: {now.strftime("%Y-%m-%d %H:%M:%S")}\n')
            for path, error in error_log:
                log.write(f"{path}\n{error}\n")


def flac_on_path():
    if shutil.which("flac") is None and sys.platform == "win32":
        choice = input(
            "flac executable is not on PATH, open environment variable settings in Windows to add it? (y/n): "
        )
        if choice == "y":
            print(
                f"""
    Step 1: Under 'User variables for {getpass.getuser()}' select 'Path' and either double click it or click on 'Edit...'
    Step 2: Click on 'New' and paste the path to the folder on your system that contains flac.exe.
            Then confirm with "OK" twice.

            Info:
            If you do not have flac installed yet, visit this website (or download it from a source you trust):
            https://xiph.org/flac/download.html
            Then click on FLAC for Windows, select the most recent "flac-x.x.x-win.zip" file, download it and unpack it.
            You can pretty much put the folder wherever you like.
            My flac executable (as of writing) for example is located in
            C:\\Program Files (x86)\\flac-1.4.3-win\\Win64
            Once you have decided on where to store it, add that path to PATH as described above.

            Note:
            You can also add the folder that contains this script to PATH in the same way
            if you want to call it from any folder.

    Step 3: Once that is done, re-run this script."""
            )
            try:
                subprocess.run(["rundll32.exe", "sysdm.cpl,EditEnvironmentVariables"])
            except subprocess.CalledProcessError:
                print(f"Error opening environment variable settings.")
            sys.exit()
        else:
            print("Exiting.")
            sys.exit()
    elif shutil.which("flac") is None:
        print("flac is not on PATH, add it and try again.")
        sys.exit()
    else:
        return


def rsgain_on_path():
    if shutil.which("rsgain") is None and sys.platform == "win32":
        choice = input(
            "rsgain executable is not on PATH, open environment variable settings in Windows to add it? (y/n): "
        )
        if choice == "y":
            print(
                f"""
    Step 1: Under 'User variables for {getpass.getuser()}' select 'Path' and either double click it or click on 'Edit...'
    Step 2: Click on 'New' and paste the path to the folder on your system that contains rsgain.exe.
            Then confirm with "OK" twice.

            Info:
            If you do not have flac installed yet, visit this website:
            https://github.com/complexlogic/rsgain/releases
            Then under Assets, select the most recent "rsgain-x.x-win64.zip" file, download it and unpack it.
            You can pretty much put the folder wherever you like.
            My rsgain executable (as of writing) for example is located in
            C:\\Program Files (x86)\\rsgain-3.5-win64
            Once you have decided on where to store it, add that path to PATH as described above.

            Note:
            You can also add the folder that contains this script to PATH in the same way
            if you want to call it from any folder.

    Step 3: Once that is done, re-run this script."""
            )
            try:
                subprocess.run(["rundll32.exe", "sysdm.cpl,EditEnvironmentVariables"])
            except subprocess.CalledProcessError:
                print(f"Error opening environment variable settings.")
            sys.exit()
        else:
            print("Exiting.")
            sys.exit()
    elif shutil.which("rsgain") is None:
        print(
            "rsgain is not on PATH, add it to PATH or execute the program again without -r."
        )
        sys.exit()
    else:
        return True


def flac_version_check():
    min_version_pattern = r"^flac (?:(1\.(?:[5-9]|1[0-9])\.\d+)|((2\.\d+\.\d+)))$"
    flac_version = subprocess.run(
        ["flac", "--version"], encoding="utf-8", stdout=subprocess.PIPE
    )
    # Check if the flac version is >=1.5.0 as multi-threading is not available in earlier versions
    if re.match(min_version_pattern, flac_version.stdout):
        return
    else:
        print(
            f"The installed flac version: {flac_version.stdout.strip()} does not support multi-threading. Install v1.5.0 or later or rerun without -j."
        )
        sys.exit()


def process_encoder_metadata(flac_files, progress):
    """
    Process all FLAC files to check and fix ENCODER metadata tags.
    Returns a count of files that had issues and how many were fixed.
    """
    files_with_issues = 0
    files_fixed = 0
    
    with tqdm(
        total=len(flac_files),
        desc="checking encoder metadata",
        unit=" files",
        disable=not progress,
        ncols=100,
    ) as pbar:
        for flac_file in flac_files:
            needs_fix, issues, fixed = check_and_fix_encoder_metadata(flac_file, fix_issues=True)
            
            if needs_fix:
                files_with_issues += 1
                if fixed:
                    files_fixed += 1
                    safe_print(f"FIXED: {flac_file} - {', '.join(issues)}")
                else:
                    safe_print(f"ISSUES: {flac_file} - {', '.join(issues)}")
            
            pbar.update(1)
            pbar.set_postfix({"issues": files_with_issues, "fixed": files_fixed})
    
    return files_with_issues, files_fixed


def main(args):
    """
    Main function to orchestrate the FLAC processing workflow.
    """
    args = parse_arguments()
    directory = args.directory
    log_to_disk = args.log
    thread_count = int(args.multi_threaded)
    progress = args.progress
    calc_rsgain = args.rsgain
    single_folder = args.single_folder
    test_run = args.test
    multi_threaded = args.j
    check_encoder = args.check_encoder

    # Validate all dependencies upfront
    missing_deps = validate_dependencies(check_encoder, calc_rsgain)
    if missing_deps:
        safe_print(f"Missing required dependencies: {', '.join(missing_deps)}")
        safe_print("Please install the missing tools and ensure they are in your PATH.")
        sys.exit(1)

    # Legacy dependency checks for interactive setup (Windows only)
    if sys.platform == "win32":
        flac_on_path()
        if calc_rsgain:
            calc_rsgain = rsgain_on_path()

    # Validate directory exists and is accessible
    if not os.path.exists(directory):
        safe_print(f"Error: Directory '{directory}' does not exist.")
        sys.exit(1)
    if not os.access(directory, os.R_OK):
        safe_print(f"Error: No read permission for directory '{directory}'.")
        sys.exit(1)

    # Collect paths of all .flac files
    safe_print(f"Scanning directory: {directory}")
    flac_files = find_flac_files(directory, single_folder, progress)
    
    if not flac_files:
        safe_print("No FLAC files found in the specified directory.")
        return

    safe_print(f"Found {len(flac_files)} FLAC files.")
    
    # Check and fix ENCODER metadata if requested
    if check_encoder:
        safe_print(f"Checking ENCODER metadata for {len(flac_files)} FLAC files...")
        files_with_issues, files_fixed = process_encoder_metadata(flac_files, progress)
        safe_print(f"ENCODER metadata check completed: {files_with_issues} files had issues, {files_fixed} were fixed.")
        
        # If only checking encoder metadata, exit here
        if not test_run and not calc_rsgain:
            return
    
    # Filter files that need re-encoding
    safe_print(f"Checking which files need re-encoding...")
    files_to_reencode = []
    skipped_count = 0
    
    with tqdm(
        total=len(flac_files),
        desc="checking files",
        unit=" files",
        disable=not progress,
        ncols=100,
    ) as pbar:
        for f in flac_files:
            pbar.set_postfix({"current": os.path.basename(f)})
            if not is_flac_1_5_or_newer(f):
                files_to_reencode.append(f)
                safe_print(f"Will re-encode: {f}")
            else:
                skipped_count += 1
                safe_print(f"Skipping {f}: already encoded with FLAC 1.5.0 or newer.")
            pbar.update(1)
    
    safe_print(f"File check complete: {len(files_to_reencode)} files need re-encoding, {skipped_count} files skipped.")
    flac_files = files_to_reencode

    if not flac_files and not calc_rsgain:
        safe_print("No files need processing.")
        return

    error_log = []
    error_count = 0

    # Calculate replay gain values and write them to the tags
    if calc_rsgain:
        safe_print("Calculating replay gain...")
        run_rsgain(directory, thread_count)

    if not test_run and flac_files:
        safe_print(f"Processing {len(flac_files)} files that need re-encoding...")
        
        # Encode files 1 at a time with multiple threads
        if multi_threaded:
            flac_version_check()
            with tqdm(
                total=len(flac_files),
                desc="encoding",
                unit="files",
                disable=not progress,
                ncols=100,
            ) as pbar:
                for i, flac_file in enumerate(flac_files):
                    safe_print(f"Processing: {flac_file}")
                    pbar.set_postfix({"current": os.path.basename(flac_file)})
                    filepath, stderr = reencode_flac(flac_file, thread_count)
                    if stderr:
                        error_log.append((filepath, stderr))
                        error_count += 1
                        safe_print(f"Error processing {filepath}: {stderr}")
                        pbar.set_postfix({"errors": error_count, "current": os.path.basename(flac_file)})
                    else:
                        safe_print(f"Successfully processed: {filepath}")
                    pbar.update(1)
        # Encode multiple files concurrently
        else:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=thread_count
            ) as executor:
                # Submit tasks to the executor
                futures = {
                    executor.submit(reencode_flac, filepath): filepath
                    for filepath in flac_files
                }

                # Track progress using tqdm
                with tqdm(
                    total=len(flac_files),
                    desc="encoding",
                    unit=" files",
                    disable=not progress,
                    ncols=100,
                ) as pbar:
                    for future in concurrent.futures.as_completed(futures):
                        original_filepath = futures[future]
                        filepath, stderr = future.result()
                        if stderr:
                            error_log.append((filepath, stderr))
                            error_count += 1
                            safe_print(f"Error processing {filepath}: {stderr}")
                            pbar.set_postfix({"errors": error_count})
                        else:
                            safe_print(f"Successfully processed: {filepath}")
                        pbar.update(1)
    elif test_run and flac_files:
        safe_print(f"Testing {len(flac_files)} files...")
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=thread_count
        ) as executor:
            # Submit tasks to the executor
            futures = {
                executor.submit(verify_flac, filepath): filepath
                for filepath in flac_files
            }

            # Track progress using tqdm
            with tqdm(
                total=len(flac_files),
                desc="verifying",
                unit=" files",
                disable=not progress,
                ncols=100,
            ) as pbar:
                for future in concurrent.futures.as_completed(futures):
                    original_filepath = futures[future]
                    filepath, stderr = future.result()
                    if stderr:
                        error_log.append((filepath, stderr))
                        error_count += 1
                        safe_print(f"Verification error for {filepath}: {stderr}")
                        pbar.set_postfix({"errors": error_count})
                    else:
                        safe_print(f"Successfully verified: {filepath}")
                    pbar.update(1)

    # Handle error logging and reporting
    if error_log:
        if log_to_disk:
            write_log(error_log)
            safe_print(f"Errors logged to {LOG_FILENAME}")
        else:
            safe_print("Errors encountered:")
            for path, error in error_log:
                safe_print(f"  {path}: {error}")
    
    # Final summary
    if flac_files:
        percentage = (error_count / len(flac_files)) * 100
        safe_print(f"\nProcessing complete: {len(flac_files)} files processed, {error_count} errors. Error rate: {percentage:.2f}%")
    else:
        safe_print("\nProcessing complete.")


if __name__ == "__main__":
    args = parse_arguments()
    try:
        main(args)
    except KeyboardInterrupt:
        print("Interrupted")
        try:
            sys.exit(130)
        except SystemExit:
            os._exit(130)

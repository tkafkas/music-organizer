import os
import shutil
import eyed3
import sys
import logging
import time
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')
    return filename.strip()

def setup_logging():
    """Set up logging configuration"""
    logging.basicConfig(
        filename='music_organizer.log',
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def get_file_signature(file_path, audiofile):
    """Generate a unique signature for a file based on ID3 tags and size"""
    try:
        file_size = os.path.getsize(file_path)
        if audiofile and audiofile.tag:
            title = audiofile.tag.title or ''
            artist = audiofile.tag.artist or ''
            album = audiofile.tag.album or ''
            return f"{title}|{artist}|{album}|{file_size}"
    except Exception:
        pass
    return None

MAX_FILES = 2000  # Maximum number of files to process in one run

def find_cover_images(file_path):
    """Find cover image files in the same directory as the music file"""
    directory = os.path.dirname(file_path)
    cover_files = []
    cover_patterns = [
        'cover', 'folder', 'album', 'albumart', 'front',
        'cd', 'disc', 'artwork', 'art', 'scan'
    ]
    
    for file in os.listdir(directory):
        if file.lower().endswith(('.jpg', '.jpeg', '.png')):
            file_lower = file.lower()
            # Check if filename matches common cover patterns
            if any(pattern in file_lower for pattern in cover_patterns):
                cover_files.append(os.path.join(directory, file))
                
    return cover_files

def extract_artist_from_tag(tag_value):
    """Extract clean artist name from a tag value"""
    if not tag_value:
        return None
    # Handle multiple artists
    artist = tag_value.split('/')[0].split(';')[0].split('feat.')[0].split('ft.')[0].strip()
    return artist if artist else None

def move_file_to_main_structure(file_path, source_dir):
    """Move a music file and its cover images to the main structure"""
    try:
        logging.info(f"Attempting to move file: {file_path}")

        # Try to extract artist from file path first
        file_dir = os.path.dirname(file_path)
        path_parts = file_dir.split(os.sep)
        potential_artist = None

        # Check if the immediate parent directory could be an artist name
        if len(path_parts) > 0 and not any(x in path_parts[-1].lower() for x in ['unknown', 'misc', 'various']):
            potential_artist = path_parts[-1]
            logging.info(f"Found potential artist '{potential_artist}' from directory name: {file_dir}")

        audiofile = eyed3.load(file_path)
        artist = None
        
        if audiofile and audiofile.tag:
            tag = audiofile.tag
            logging.info(f"Processing tags for: {file_path}")

            # 1. Try album artist
            if tag.album_artist:
                artist = extract_artist_from_tag(tag.album_artist)
                if artist:
                    logging.info(f"Using album_artist tag: '{artist}'")
                    tag_source_counts['album_artist'] += 1

            # 2. Try main artist tag
            if not artist and tag.artist:
                artist = extract_artist_from_tag(tag.artist)
                if artist:
                    logging.info(f"Using artist tag: '{artist}'")
                    tag_source_counts['artist'] += 1

            # 3. Try performer tags
            if not artist and hasattr(tag, 'performer'):
                try:
                    performers = tag.performer
                    if isinstance(performers, list):
                        artist = extract_artist_from_tag(performers[0])
                    else:
                        artist = extract_artist_from_tag(performers)
                    if artist:
                        logging.info(f"Using performer tag: '{artist}'")
                        tag_source_counts['performer'] += 1
                except Exception as e:
                    logging.error(f"Error processing performer tag: {str(e)}")

        # Try to extract from filename if no artist found from tags
        if not artist:
            filename = os.path.basename(file_path)
            name = os.path.splitext(filename)[0]
            
            # Common patterns in filenames
            separators = [' - ', '-', '_']
            for sep in separators:
                if sep in name:
                    parts = name.split(sep, 1)
                    potential_artist_from_filename = parts[0].strip()
                    if potential_artist_from_filename and len(potential_artist_from_filename) > 1:
                        logging.info(f"Found potential artist '{potential_artist_from_filename}' from filename: {filename}")
                        artist = potential_artist_from_filename
                        tag_source_counts['filename'] += 1
                        break

        # Use artist from directory name as last resort
        if not artist and potential_artist:
            artist = potential_artist
            logging.info(f"Using directory name as artist: '{artist}'")
            tag_source_counts['directory'] += 1

        if not artist:
            logging.warning(f"No artist found for file: {file_path}")

            # Log if we had to process multiple artists
            if artist and ('/' in str(tag.artist) or ';' in str(tag.artist) or 'feat.' in str(tag.artist).lower() or 'ft.' in str(tag.artist).lower()):
                logging.info(f"Multiple artists found in: {file_path}")
                logging.info(f"Original: '{tag.artist}' -> Using: '{artist}'")

            if not artist:
                tag_source_counts['unknown'] += 1
                artist = "Unknown Artist"
            album = audiofile.tag.album or "Unknown Album"
            year = audiofile.tag.best_release_date
            
            artist = sanitize_filename(artist)
            album = sanitize_filename(album)
            year_str = f" ({year.year})" if year else ""
            
            new_dir = os.path.join(source_dir, artist, f"{album}{year_str}")
            os.makedirs(new_dir, exist_ok=True)
            new_file_path = os.path.join(new_dir, os.path.basename(file_path))
            
            moved = False
            if file_path != new_file_path and os.path.exists(file_path):
                # Move the music file
                shutil.move(file_path, new_file_path)
                moved = True
                
                # Find and move cover images
                cover_files = find_cover_images(file_path)
                for cover_file in cover_files:
                    try:
                        new_cover_path = os.path.join(new_dir, os.path.basename(cover_file))
                        if not os.path.exists(new_cover_path):
                            shutil.move(cover_file, new_cover_path)
                            logging.info(f"Moved cover image: {cover_file} -> {new_cover_path}")
                    except Exception as e:
                        logging.error(f"Error moving cover image {cover_file}: {str(e)}")
                        
            return moved
    except Exception as e:
        logging.error(f"Error moving file {file_path}: {str(e)}")
    return False

def process_file(file_info):
    """Process a single file and return its signature"""
    global processed_count
    file_path, total_files, current = file_info
    try:
        # Skip problematic files faster
        try:
            size = os.path.getsize(file_path)
            if size > 50 * 1024 * 1024:  # Skip files larger than 50MB
                logging.warning(f"Skipping large file: {file_path}")
                processed_count += 1
                print(f"\rScanning files: {processed_count}/{total_files} ({(processed_count/total_files)*100:.1f}%)", end="", flush=True)
                return None
        except OSError:
            logging.error(f"Cannot access file: {file_path}")
            return None
            
        # Add a shorter timeout for eyed3.load
        start_time = time.time()
        try:
            audiofile = eyed3.load(file_path)
            if not audiofile or not audiofile.tag:
                def clean_metadata(text):
                    """Clean up extracted metadata text"""
                    # Remove common file prefixes/suffixes
                    text = re.sub(r'^\d+\.?\s*', '', text)  # Remove leading numbers
                    text = re.sub(r'\([^)]*\)', '', text)   # Remove parentheses content
                    text = re.sub(r'\[[^\]]*\]', '', text)  # Remove bracket content
                    text = re.sub(r'\{[^}]*\}', '', text)   # Remove curly brace content
                    text = re.sub(r'(320|256|192|128)kbps', '', text, flags=re.IGNORECASE)  # Remove bitrate
                    text = re.sub(r'mp3|flac|wav', '', text, flags=re.IGNORECASE)  # Remove format
                    return text.strip()

                # Try to extract info from filename
                filename = os.path.basename(file_path)
                name = os.path.splitext(filename)[0]
                
                # Try different common filename patterns
                patterns = [
                    lambda n: n.replace('_', ' ').replace('-', ' - ').split(' - '),  # Artist - Title
                    lambda n: n.split(' - '),  # Simple dash separation
                    lambda n: n.split('-'),    # Simple hyphen
                    lambda n: n.split('_'),    # Underscore separation
                    lambda n: re.split(r'\s+(?=\d{1,2}\s)', n),  # Track number separation
                    lambda n: [n[:n.find(' ')], n[n.find(' ')+1:]]  # First space separation
                ]
                
                parts = None
                for pattern in patterns:
                    try:
                        candidate_parts = pattern(name)
                        if len(candidate_parts) >= 2:
                            # Clean up each part
                            parts = [clean_metadata(p) for p in candidate_parts]
                            # Filter out empty parts and very short strings (likely not valid metadata)
                            parts = [p for p in parts if len(p) > 2]
                            if len(parts) >= 2:
                                break
                    except:
                        continue
                
                if parts and len(parts) >= 2:  # If we have at least artist and title
                    if not audiofile:
                        audiofile = eyed3.Mp3AudioFile(file_path)
                    if not audiofile.tag:
                        audiofile.initTag()
                    audiofile.tag.artist = parts[0].strip()
                    audiofile.tag.title = parts[1].strip()
                    if len(parts) > 2:  # If we have album info
                        audiofile.tag.album = parts[2].strip()
                    try:
                        audiofile.tag.save()
                        global tags_extracted_count, tag_source_counts
                        tags_extracted_count += 1
                        tag_source_counts['filename'] += 1
                        logging.info(f"Added tags to file from filename: {file_path}")
                    except Exception as e:
                        logging.error(f"Error saving tags for {file_path}: {str(e)}")
                else:
                    logging.warning(f"No valid tags in file and couldn't parse filename: {file_path}")
                    return None
        except Exception as e:
            logging.error(f"Failed to load file {file_path}: {str(e)}")
            return None
        
        # Reduce timeout to 2 seconds
        if time.time() - start_time > 2:
            logging.warning(f"Timeout loading file: {file_path}")
            processed_count += 1
            print(f"\rScanning files: {processed_count}/{total_files} ({(processed_count/total_files)*100:.1f}%)", end="", flush=True)
            return None
            
        signature = get_file_signature(file_path, audiofile)
        processed_count += 1
        
        if processed_count % 5 == 0 or processed_count == total_files:  # Update progress more frequently
            print(f"\rScanning files: {processed_count}/{total_files} ({(processed_count/total_files)*100:.1f}%)", end="", flush=True)
            
        if signature:
            return (signature, (file_path, audiofile))
            
    except Exception as e:
        processed_count += 1
        logging.error(f"Error processing {file_path}: {str(e)}")
        print(f"\rScanning files: {processed_count}/{total_files} ({(processed_count/total_files)*100:.1f}%)", end="", flush=True)
    return None

# Global counter for processed files
processed_count = 0
tags_extracted_count = 0
tag_source_counts = {
    'album_artist': 0,
    'artist': 0,
    'performer': 0,
    'filename': 0,
    'directory': 0,
    'unknown': 0
}

def should_remove_dir(dirpath):
    """Check if directory should be removed (empty or contains only unwanted files)"""
    try:
        items = os.listdir(dirpath)
        if not items:  # Empty directory
            return True
            
        for item in items:
            item_path = os.path.join(dirpath, item)
            if os.path.isdir(item_path):
                return False  # Keep directories with subdirectories
            if item.lower().endswith('.mp3'):
                return False  # Keep directories with MP3s
                
        # If we get here, directory has no MP3s and no subdirectories
        # Check if it only contains thumb/txt files or images
        has_only_unwanted = True
        for item in items:
            ext = os.path.splitext(item.lower())[1]
            if not ext in ['.txt', '.db', '.ini', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.thumb']:
                has_only_unwanted = False
                break
                
        return has_only_unwanted
    except Exception:
        return False

def remove_empty_dirs(path):
    """Remove empty directories and directories with only non-MP3 files"""
    removed = set()
    processed_count = 0
    total_moved = 0

    print("\nMoving remaining MP3 files to main structure...")
    # First, try to move any MP3s still in subdirectories
    for dirpath, dirnames, filenames in os.walk(path):
        if dirpath == path:  # Skip the root directory
            continue
        
        mp3_files = [f for f in filenames if f.lower().endswith('.mp3')]
        if mp3_files:
            for mp3_file in mp3_files:
                file_path = os.path.join(dirpath, mp3_file)
                if move_file_to_main_structure(file_path, path):
                    total_moved += 1
                processed_count += 1
                if processed_count % 10 == 0:
                    print(f"\rProcessed {processed_count} files, moved {total_moved} files", end="", flush=True)

    print(f"\nMoved {total_moved} files to main structure")

    # Now remove directories that are either empty or contain only non-MP3 files
    print("\nRemoving empty directories and directories with no MP3s...")
    for dirpath, dirnames, filenames in os.walk(path, topdown=False):
        if dirpath == path:  # Skip the root directory
            continue

        try:
            if should_remove_dir(dirpath):
                # Delete all non-MP3 files first
                for file in filenames:
                    try:
                        os.remove(os.path.join(dirpath, file))
                    except Exception as e:
                        logging.error(f"Error deleting file {file}: {str(e)}")
                
                # Then remove the directory
                os.rmdir(dirpath)
                removed.add(dirpath)
                print(f"Removed directory with non-MP3 files: {dirpath}")
                
        except OSError as e:
            logging.error(f"Error removing directory {dirpath}: {str(e)}")

    return len(removed)

def organize_music(source_dir="D:\\Music", max_files=MAX_FILES, unknown_only=False):
    """Organize music files into first-level artist/album structure"""
    global processed_count, tags_extracted_count, tag_source_counts
    processed_count = 0
    tags_extracted_count = 0
    tag_source_counts = {
        'album_artist': 0,
        'artist': 0,
        'performer': 0,
        'filename': 0,
        'directory': 0,
        'unknown': 0
    }
    print("\nInitializing...")
    setup_logging()
    print(f"Starting music organization from: {source_dir}")
    logging.info(f"Starting music organization from: {source_dir}")
    
    # Check if source directory exists
    if not os.path.exists(source_dir):
        print(f"Error: Directory {source_dir} does not exist!")
        return

    # Dictionary to store file signatures for duplicate detection
    file_signatures = defaultdict(list)

    # Collect all MP3 files
    print("Collecting MP3 files...")
    mp3_files = []
    try:
        for root, dirs, files in os.walk(source_dir):
            if unknown_only:
                # Only process files in Unknown Artist directories
                if "Unknown Artist" not in root:
                    continue
                logging.info(f"Processing Unknown Artist directory: {root}")
            
            mp3_files.extend(
                (os.path.join(root, file), len(mp3_files) + 1)
                for file in files
                if file.lower().endswith('.mp3')
            )
    except Exception as e:
        print(f"\nError collecting files: {str(e)}")
        return

    total_files = len(mp3_files)
    if total_files == 0:
        print("No MP3 files found in the directory!")
        return
        
    if total_files > max_files:
        print(f"\nWARNING: Found {total_files} files, but will only process first {max_files} files")
        print("Run the script multiple times to process all files")
        mp3_files = mp3_files[:max_files]
        total_files = max_files

    # Adjust number of workers based on file count, but keep it reasonable
    num_workers = min(max(4, total_files // 1000), 8)
    print(f"Found {total_files} MP3 files. Starting scan with {num_workers} parallel workers...")

    # Process files with thread pool
    scan_start_time = time.time()
    batch_size = 100  # Process files in smaller batches
    
    try:
        for i in range(0, len(mp3_files), batch_size):
            if time.time() - scan_start_time > 300:  # 5 minutes timeout
                print("\nScanning taking too long, stopping...")
                return
                
            batch = mp3_files[i:i+batch_size]
            current_batch = f"Batch {i//batch_size + 1}/{(len(mp3_files) + batch_size - 1)//batch_size}"
            print(f"\n{current_batch}")
            
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = [
                    executor.submit(process_file, (file_path, total_files, idx))
                    for idx, (file_path, _) in enumerate(batch, i + 1)
                ]

                for future in as_completed(futures):
                    try:
                        result = future.result(timeout=5)  # Add timeout for each future
                        if result and len(result) == 2:  # Make sure result has the expected format
                            signature, file_info = result
                            file_signatures[signature].append(file_info)
                    except TimeoutError:
                        logging.warning("Timeout processing batch item")
                        continue
                    except Exception as e:
                        logging.error(f"Error processing file: {str(e)}")
                        continue
                        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user...")
        return
    except Exception as e:
        print(f"\nError during scanning: {str(e)}")
        return

    print(f"\nScan complete! Processed {processed_count} files")
    print("\nTag sources used for artist names:")
    print(f"- Album Artist tag: {tag_source_counts['album_artist']} files")
    print(f"- Artist tag: {tag_source_counts['artist']} files")
    print(f"- Performer tag: {tag_source_counts['performer']} files")
    print(f"- Extracted from filename: {tag_source_counts['filename']} files")
    print(f"- Extracted from directory: {tag_source_counts['directory']} files")
    print(f"- Files marked as Unknown Artist: {tag_source_counts['unknown']} files")
    if tags_extracted_count > 0:
        print(f"\nSuccessfully extracted and added tags for {tags_extracted_count} files from their filenames")

    # Report scanning results
    total_duplicates = sum(len(files) - 1 for files in file_signatures.values() if len(files) > 1)
    print(f"\nFound {total_duplicates} duplicate files")
    
    # Second pass: organize files and handle duplicates
    print("\nOrganizing files and removing duplicates...")
    processed_files = set()
    total_processed = 0
    total_to_process = sum(len(files) for files in file_signatures.values())
    
    for signature, files in file_signatures.items():
        valid_files = [f for f in files if f and len(f) == 2]  # Filter out any invalid entries
        if len(valid_files) > 1:
            # Keep the first file, delete the rest
            kept_file = valid_files[0]
            for duplicate in valid_files[1:]:
                try:
                    logging.info(f"Duplicate found: {duplicate[0]} (matches {kept_file[0]})")
                    if os.path.exists(duplicate[0]):  # Check if file still exists
                        os.remove(duplicate[0])
                        print(f"\rDeleted duplicate: {os.path.basename(duplicate[0])}")
                except Exception as e:
                    logging.error(f"Error deleting duplicate: {str(e)}")
        
        if not valid_files:  # Skip if no valid files
            continue

        # Process the kept file (or single file if no duplicates)
        file_path, audiofile = valid_files[0]
        if file_path in processed_files:
            total_processed += 1
            print(f"\rProcessing files: {total_processed}/{total_to_process} ({(total_processed/total_to_process)*100:.1f}%)", end="")
            continue
            
        try:
            if audiofile and audiofile.tag:
                # Get metadata
                # Try different artist tags in order of preference
                artist = None
                tag = audiofile.tag

                # 1. Try album artist
                if tag.album_artist:
                    artist = extract_artist_from_tag(tag.album_artist)
                    if artist:
                        logging.info(f"Using album_artist tag for: {file_path}")

                # 2. Try main artist tag
                if not artist and tag.artist:
                    artist = extract_artist_from_tag(tag.artist)
                    if artist:
                        logging.info(f"Using artist tag for: {file_path}")

                # 3. Try performer tags
                if not artist and hasattr(tag, 'performer'):
                    try:
                        performers = tag.performer
                        if isinstance(performers, list):
                            artist = extract_artist_from_tag(performers[0])
                        else:
                            artist = extract_artist_from_tag(performers)
                        if artist:
                            logging.info(f"Using performer tag for: {file_path}")
                    except:
                        pass

                # Log if we had to process multiple artists
                if artist and ('/' in str(tag.artist) or ';' in str(tag.artist) or 'feat.' in str(tag.artist).lower() or 'ft.' in str(tag.artist).lower()):
                    logging.info(f"Multiple artists found in: {file_path}")
                    logging.info(f"Original: '{tag.artist}' -> Using: '{artist}'")
                
                album = audiofile.tag.album
                year = audiofile.tag.best_release_date
                
                # Handle missing metadata
                if not artist:
                    tag_source_counts['unknown'] += 1
                    artist = "Unknown Artist"
                if not album:
                    album = "Unknown Album"
                    
                # Sanitize names
                artist = sanitize_filename(artist)
                album = sanitize_filename(album)
                
                # Create year string if available
                year_str = f" ({year.year})" if year else ""
                
                # Create new directory path directly under source_dir
                # (ignore any existing subdirectory structure)
                new_dir = os.path.join(source_dir, artist, f"{album}{year_str}")
                os.makedirs(new_dir, exist_ok=True)
                
                # Create new file path
                new_file_path = os.path.join(new_dir, os.path.basename(file_path))
                
                # Move file if it's not already in the correct location
                if file_path != new_file_path:
                    total_processed += 1
                    print(f"\rProcessing files: {total_processed}/{total_to_process} ({(total_processed/total_to_process)*100:.1f}%)", end="")
                    
                    if file_path != new_file_path and os.path.exists(file_path):
                        shutil.move(file_path, new_file_path)
                    
                    processed_files.add(file_path)
                    
        except Exception as e:
            logging.error(f"Error processing {file_path}: {str(e)}")

def move_unknown_albums(source_dir):
    """Move unknown album folders under artist directories to a root Unknown Album folder"""
    print("\nMoving unknown albums to root folder...")
    unknown_album_root = os.path.join(source_dir, "Unknown Album")
    os.makedirs(unknown_album_root, exist_ok=True)
    
    moved_count = 0
    for artist_dir in os.listdir(source_dir):
        artist_path = os.path.join(source_dir, artist_dir)
        if not os.path.isdir(artist_path):
            continue
            
        for album_dir in os.listdir(artist_path):
            if album_dir == "Unknown Album":
                album_path = os.path.join(artist_path, album_dir)
                if not os.path.isdir(album_path):
                    continue
                    
                # Create artist folder under Unknown Album root
                artist_unknown_path = os.path.join(unknown_album_root, artist_dir)
                os.makedirs(artist_unknown_path, exist_ok=True)
                
                # Move all files from the unknown album to the new location
                for file_name in os.listdir(album_path):
                    old_file_path = os.path.join(album_path, file_name)
                    new_file_path = os.path.join(artist_unknown_path, file_name)
                    try:
                        if not os.path.exists(new_file_path):
                            shutil.move(old_file_path, new_file_path)
                            moved_count += 1
                            print(f"\rMoved {moved_count} files", end="", flush=True)
                    except Exception as e:
                        logging.error(f"Error moving file {old_file_path}: {str(e)}")
                
                # Remove the original empty unknown album directory
                try:
                    os.rmdir(album_path)
                except Exception as e:
                    logging.error(f"Error removing directory {album_path}: {str(e)}")
    
    print(f"\nMoved {moved_count} files to Unknown Album root folder")

def get_source_directory():
    """Get the source directory from user input or command line argument"""
    # Check command line argument first
    if len(sys.argv) > 1:
        return sys.argv[1]
    
    default_dir = "D:\\Music"
    print(f"\nDefault directory is: {default_dir}")
    choice = input("Would you like to use a different directory? (y/n): ").lower().strip()
    
    if choice == 'y':
        while True:
            custom_dir = input("\nEnter the full path to your music directory: ").strip()
            if os.path.exists(custom_dir):
                return custom_dir
            print("Error: Directory does not exist. Please try again.")
    
    return default_dir

def main():
    print("MP3 Music Organizer")
    print("-----------------")
    
    # Get the source directory
    source_dir = get_source_directory()
    
    print(f"\nTarget directory: {source_dir}")
    print("This tool will:")
    print("1. Scan for duplicate MP3s (based on ID3 tags and file size)")
    print("2. Remove duplicates (keeping the first occurrence)")
    print("3. Organize remaining files into Artist/Album (Year) structure")
    print("4. Move all unknown albums under their respective artists to a root 'Unknown Album' folder")
    print("5. Remove empty directories")
    print("\nAll actions will be logged to music_organizer.log")
    input("Press Enter to start organizing or Ctrl+C to cancel...")
    
    organize_music(source_dir)
    
    # Move unknown albums to root folder
    print("\nMoving unknown albums to root folder...")
    move_unknown_albums(source_dir)
    
    print("\nCleaning up empty directories...")
    removed_count = remove_empty_dirs(source_dir)
    print(f"Removed {removed_count} empty directories")
    
    print("\nOrganization complete!")
    print("Check music_organizer.log for detailed information about duplicates and any errors.")

if __name__ == "__main__":
    main()
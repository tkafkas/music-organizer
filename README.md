# Music Organizer

A Python script that automatically organizes your music collection by analyzing MP3 files, extracting metadata, and organizing them into a clean artist/album structure.

## Features

- Intelligent artist name extraction from multiple sources:
  - Album Artist tag
  - Artist tag
  - Performer tag
  - Filename patterns
  - Directory names
- Automatic album organization
- Cover image handling and relocation
- Duplicate file detection
- Tag extraction from filenames when metadata is missing
- Multi-threaded processing for better performance
- Support for large music collections (batch processing)
- Comprehensive logging system
- Empty directory cleanup
- Unknown artist handling

## Requirements

- Python 3.x
- eyed3 library (for MP3 metadata handling)
- Windows OS

## Installation

1. Clone or download this repository
2. Install the required Python package:
```bash
pip install eyed3
```

## Usage

### Simple Method
Double-click `run_music_organizer.bat` to start the program with default settings.

### Command Line Options

The script can be run directly with Python and supports several parameters:

```python
python music_organizer_v2.py [options]
```

Parameters:
- `source_dir`: Directory containing music files (default: "D:\Music")
- `max_files`: Maximum number of files to process in one run (default: 2000)
- `unknown_only`: Process only files in "Unknown Artist" directories (default: False)

## How It Works

1. **File Scanning**:
   - Recursively scans the source directory for MP3 files
   - Analyzes each file's metadata using eyed3
   - Attempts to extract artist and album information

2. **Artist Detection Priority**:
   - Album Artist tag
   - Main Artist tag
   - Performer tag
   - Filename pattern matching
   - Parent directory name
   - Falls back to "Unknown Artist" if no information found

3. **Organization Process**:
   - Creates artist directories
   - Creates album subdirectories (with year if available)
   - Moves MP3 files to appropriate locations
   - Relocates associated cover images
   - Removes empty directories

4. **Duplicate Handling**:
   - Generates unique signatures based on metadata and file size
   - Identifies and reports duplicate files
   - Keeps track of processed files to avoid redundancy

5. **Cover Image Management**:
   - Identifies cover images using common naming patterns
   - Moves cover images along with their associated music files
   - Supports various image formats (jpg, jpeg, png)

## File Structure

The script organizes music into the following structure:
```
Music/
├── Artist Name/
│   ├── Album Name (Year)/
│   │   ├── song1.mp3
│   │   ├── song2.mp3
│   │   └── cover.jpg
│   └── Another Album/
└── Another Artist/
```

## Logging

The script creates a `music_organizer.log` file that contains detailed information about:
- Files processed
- Metadata extraction results
- Error messages
- Directory operations
- Tag sources used

## Notes

- The script processes a maximum of 2000 files per run by default to manage memory usage
- For large collections, run the script multiple times
- Files larger than 50MB are automatically skipped
- The script attempts to extract tags from filenames if no metadata is present
- Empty directories and directories containing only non-MP3 files are removed during cleanup

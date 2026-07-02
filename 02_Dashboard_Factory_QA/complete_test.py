#!/usr/bin/env python3
"""
Complete test suite for Dashboard Factory Tool
Tests all major endpoints with the Occupancy Level dashboard
"""

import requests
import json
import time
import os
from datetime import datetime

BASE_URL = "http://127.0.0.1:5555"
TEST_FILE = "/Users/RGaneshan/Downloads/Occupancy Level 2 - Seats and Trending (1).twbx"

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

def print_header(text):
    """Print a formatted header."""
    print(f"\n{BOLD}{BLUE}{'='*80}{RESET}")
    print(f"{BOLD}{BLUE}{text.center(80)}{RESET}")
    print(f"{BOLD}{BLUE}{'='*80}{RESET}\n")

def print_success(text):
    """Print success message."""
    print(f"{GREEN}✅ {text}{RESET}")

def print_error(text):
    """Print error message."""
    print(f"{RED}❌ {text}{RESET}")

def print_info(text):
    """Print info message."""
    print(f"{BLUE}ℹ️  {text}{RESET}")

def print_warning(text):
    """Print warning message."""
    print(f"{YELLOW}⚠️  {text}{RESET}")

# ============================================================================
# TEST 1: HEALTH CHECK
# ============================================================================

def test_health_check():
    """Test server health."""
    print_header("TEST 1: HEALTH CHECK")
    
    try:
        response = requests.get(f"{BASE_URL}/health")
        data = response.json()
        
        if response.status_code == 200:
            print_success(f"Server is healthy")
            print_info(f"DB Updater Available: {data.get('db_updater_available')}")
            return True
        else:
            print_error(f"Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"Connection error: {e}")
        return False

# ============================================================================
# TEST 2: FILE UPLOAD
# ============================================================================

def test_file_upload():
    """Test file upload endpoint."""
    print_header("TEST 2: FILE UPLOAD")
    
    if not os.path.exists(TEST_FILE):
        print_error(f"Test file not found: {TEST_FILE}")
        return None
    
    file_size = os.path.getsize(TEST_FILE) / (1024 * 1024)
    print_info(f"Uploading: {os.path.basename(TEST_FILE)} ({file_size:.2f} MB)")
    
    try:
        with open(TEST_FILE, 'rb') as f:
            files = {'file': f}
            response = requests.post(f"{BASE_URL}/api/upload", files=files)
        
        if response.status_code == 200:
            data = response.json()
            print_success(f"File uploaded successfully")
            print_info(f"File ID: {data['file_id']}")
            print_info(f"Filepath: {data['filepath']}")
            print_info(f"Original Name: {data['original_filename']}")
            return data
        else:
            print_error(f"Upload failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print_error(f"Upload error: {e}")
        return None

# ============================================================================
# TEST 3: GET CALCULATED FIELDS
# ============================================================================

def test_get_calculated_fields(filepath):
    """Test getting calculated fields."""
    print_header("TEST 3: GET CALCULATED FIELDS")
    
    print_info(f"Analyzing workbook for calculated fields...")
    
    try:
        payload = {"filepath": filepath}
        response = requests.post(f"{BASE_URL}/api/get-calculated-fields", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            total = data.get('total_fields', 0)
            fields = data.get('fields', [])
            
            print_success(f"Found {total} calculated field(s)")
            
            if fields:
                print_info(f"\nFirst 5 calculated fields:")
                for i, field in enumerate(fields[:5], 1):
                    print(f"  {i}. {field['name']} ({field['caption']})")
                    print(f"     Datasource: {field['datasource']}")
            
            return data
        else:
            print_error(f"Failed to get calculated fields: {response.status_code}")
            return None
    except Exception as e:
        print_error(f"Error: {e}")
        return None

# ============================================================================
# TEST 4: SEARCH CALCULATED FIELDS
# ============================================================================

def test_search_calculated_fields(filepath):
    """Test searching calculated fields."""
    print_header("TEST 4: SEARCH CALCULATED FIELDS")
    
    search_terms = ["Occupancy", "Rate", "Seats"]
    
    for search_term in search_terms:
        print_info(f"Searching for: '{search_term}'")
        
        try:
            payload = {
                "filepath": filepath,
                "search_term": search_term
            }
            response = requests.post(f"{BASE_URL}/api/search-calculated-fields", json=payload)
            
            if response.status_code == 200:
                data = response.json()
                matches = data.get('matches_found', 0)
                exact = data.get('exact_matches', 0)
                
                if matches > 0:
                    print_success(f"Found {matches} match(es) ({exact} exact)")
                    results = data.get('results', [])
                    if results:
                        print(f"\n  Top result:")
                        r = results[0]
                        print(f"    Name: {r.get('name')}")
                        print(f"    Caption: {r.get('caption')}")
                        print(f"    Formula: {r.get('formula')}")
                else:
                    print_warning(f"No matches found for '{search_term}'")
            else:
                print_error(f"Search failed: {response.status_code}")
        
        except Exception as e:
            print_error(f"Error: {e}")

# ============================================================================
# TEST 5: APPLY FILTERS
# ============================================================================

def test_apply_filters(filepath, original_filename):
    """Test applying filter formatting."""
    print_header("TEST 5: APPLY FILTERS FORMATTING")
    
    print_info(f"Applying custom filter styling...")
    
    try:
        payload = {
            "filepath": filepath,
            "original_filename": original_filename,
            "apply_filters": True,
            "apply_dashboard_titles": False,
            "apply_worksheet_titles": False,
            "filters_config": {
                "quick-filter-title": {
                    "color": "#435254",
                    "font-family": "Calibre",
                    "font-size": "11"
                },
                "quick-filter": {
                    "color": "#000000",
                    "font-family": "Calibre",
                    "font-size": "10"
                }
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/process", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            job_id = data['job_id']
            print_success(f"Filter formatting job started")
            print_info(f"Job ID: {job_id}")
            
            # Monitor job
            result = monitor_job(job_id)
            return result
        else:
            print_error(f"Failed to start job: {response.status_code}")
            return None
    except Exception as e:
        print_error(f"Error: {e}")
        return None

# ============================================================================
# TEST 6: APPLY DASHBOARD TITLES
# ============================================================================

def test_apply_dashboard_titles(filepath, original_filename):
    """Test applying dashboard title formatting."""
    print_header("TEST 6: APPLY DASHBOARD TITLES")
    
    print_info(f"Applying dashboard title formatting...")
    
    try:
        payload = {
            "filepath": filepath,
            "original_filename": original_filename,
            "apply_filters": False,
            "apply_dashboard_titles": True,
            "apply_worksheet_titles": False,
            "dashboard_config": {
                "font_name": "Calibre Medium",
                "font_size": "30",
                "font_color": "#012A2D"
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/process", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            job_id = data['job_id']
            print_success(f"Dashboard title job started")
            print_info(f"Job ID: {job_id}")
            
            # Monitor job
            result = monitor_job(job_id)
            return result
        else:
            print_error(f"Failed to start job: {response.status_code}")
            return None
    except Exception as e:
        print_error(f"Error: {e}")
        return None

# ============================================================================
# TEST 7: APPLY WORKSHEET TITLES
# ============================================================================

def test_apply_worksheet_titles(filepath, original_filename):
    """Test applying worksheet title formatting."""
    print_header("TEST 7: APPLY WORKSHEET TITLES")
    
    print_info(f"Applying worksheet title formatting...")
    
    try:
        payload = {
            "filepath": filepath,
            "original_filename": original_filename,
            "apply_filters": False,
            "apply_dashboard_titles": False,
            "apply_worksheet_titles": True,
            "worksheet_titles_config": {
                "font_size": "15",
                "font_family": "Calibre",
                "color": "#435254",
                "font_style": "normal"
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/process", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            job_id = data['job_id']
            print_success(f"Worksheet title job started")
            print_info(f"Job ID: {job_id}")
            
            # Monitor job
            result = monitor_job(job_id)
            return result
        else:
            print_error(f"Failed to start job: {response.status_code}")
            return None
    except Exception as e:
        print_error(f"Error: {e}")
        return None

# ============================================================================
# TEST 8: APPLY ALL OPERATIONS
# ============================================================================

def test_apply_all_operations(filepath, original_filename):
    """Test applying ALL operations at once."""
    print_header("TEST 8: APPLY ALL OPERATIONS")
    
    print_info(f"Applying ALL formatting operations...")
    print_info(f"  • Filters")
    print_info(f"  • Dashboard Titles")
    print_info(f"  • Worksheet Titles")
    print_info(f"  • Dashboard Sizes")
    print_info(f"  • Hide Used Worksheets")
    print_info(f"  • Delete Phone Layouts")
    
    try:
        payload = {
            "filepath": filepath,
            "original_filename": original_filename,
            "apply_filters": True,
            "apply_dashboard_titles": True,
            "apply_worksheet_titles": True,
            "apply_dashboard_sizes": True,
            "apply_hide_used_worksheets": True,
            "apply_delete_phone_layouts": True,
            "apply_filter_values_relevant": False,
            "apply_filter_type_dropdown": False,
            "filters_config": {
                "quick-filter-title": {
                    "color": "#435254",
                    "font-family": "Calibre",
                    "font-size": "11"
                },
                "quick-filter": {
                    "color": "#000000",
                    "font-family": "Calibre",
                    "font-size": "10"
                }
            },
            "worksheet_titles_config": {
                "font_size": "15",
                "font_family": "Calibre",
                "color": "#435254",
                "font_style": "normal"
            },
            "dashboard_config": {
                "font_name": "Calibre Medium",
                "font_size": "30",
                "font_color": "#012A2D"
            },
            "dashboard_sizes_config": {
                "width": "1366",
                "height": "1000",
                "sizing_mode": "fixed"
            }
        }
        
        response = requests.post(f"{BASE_URL}/api/process", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            job_id = data['job_id']
            print_success(f"Complete formatting job started")
            print_info(f"Job ID: {job_id}")
            
            # Monitor job
            result = monitor_job(job_id, max_wait=300)
            return result
        else:
            print_error(f"Failed to start job: {response.status_code}")
            return None
    except Exception as e:
        print_error(f"Error: {e}")
        return None

# ============================================================================
# HELPER: MONITOR JOB
# ============================================================================

def monitor_job(job_id, max_wait=120):
    """Monitor a job until completion."""
    print_info(f"\nMonitoring job progress...")
    
    start_time = time.time()
    last_progress = -1
    
    while time.time() - start_time < max_wait:
        try:
            response = requests.get(f"{BASE_URL}/api/job-status/{job_id}")
            
            if response.status_code == 200:
                data = response.json()
                status = data.get('status', 'unknown')
                progress = data.get('progress', 0)
                
                # Print progress update if it changed
                if progress != last_progress:
                    print(f"\r  Progress: [{progress:3d}%] Status: {status:<12}", end='', flush=True)
                    last_progress = progress
                
                # Print steps
                if 'steps' in data and data['steps']:
                    print()  # New line
                    for step in data['steps']:
                        step_status = step.get('status', 'unknown')
                        step_icon = '✅' if step_status == 'completed' else '⏳' if step_status == 'in-progress' else '❌'
                        print(f"    {step_icon} {step.get('name')} - {step_status}")
                
                # Check if complete
                if status in ['success', 'error']:
                    print()  # New line
                    print()  # Blank line
                    
                    if status == 'success':
                        print_success(f"Job completed successfully!")
                        print_info(f"Output Directory: {data.get('output_dir')}")
                        print_info(f"Output File: {data.get('output_file')}")
                        
                        # Verify output file exists
                        output_file = data.get('output_file')
                        if output_file and os.path.exists(output_file):
                            file_size = os.path.getsize(output_file) / (1024 * 1024)
                            print_success(f"Output file verified ({file_size:.2f} MB)")
                        else:
                            print_warning(f"Output file not found at expected location")
                    else:
                        print_error(f"Job failed!")
                        print_error(f"Message: {data.get('message')}")
                    
                    return data
                
                time.sleep(1)
            else:
                print_error(f"Failed to get job status: {response.status_code}")
                return None
        
        except Exception as e:
            print_error(f"Error monitoring job: {e}")
            return None
    
    print()
    print_error(f"Job timeout after {max_wait} seconds")
    return None

# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

def main():
    """Run all tests."""
    print_header("DASHBOARD FACTORY TOOL - COMPLETE TEST SUITE")
    print(f"Test File: {os.path.basename(TEST_FILE)}")
    print(f"Server: {BASE_URL}")
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Test 1: Health Check
    if not test_health_check():
        print_error("Server is not responding. Please start the Flask server:")
        print(f"  cd /Users/RGaneshan/Documents/Dashboard\\ Factory\\ Tool\\ V1\\ 2/Tableau\\ QA\\ Compliance")
        print(f"  python3 app.py")
        return
    
    # Test 2: Upload
    upload_data = test_file_upload()
    if not upload_data:
        print_error("Upload failed. Cannot continue.")
        return
    
    filepath = upload_data['filepath']
    original_filename = upload_data['original_filename']
    
    # Test 3: Get Calculated Fields
    test_get_calculated_fields(filepath)
    
    # Test 4: Search Calculated Fields
    test_search_calculated_fields(filepath)
    
    # Test 5: Apply Filters
    print_header("TESTING INDIVIDUAL OPERATIONS")
    test_apply_filters(filepath, original_filename)
    
    # Test 6: Apply Dashboard Titles
    test_apply_dashboard_titles(filepath, original_filename)
    
    # Test 7: Apply Worksheet Titles
    test_apply_worksheet_titles(filepath, original_filename)
    
    # Test 8: Apply All Operations
    print_header("TESTING COMBINED OPERATIONS")
    test_apply_all_operations(filepath, original_filename)
    
    # Summary
    print_header("TEST SUITE COMPLETE")
    print(f"Output Directory: {os.path.expanduser('~/Desktop/Formatted_Workbooks')}")
    print(f"\nAll formatted workbooks are saved to: ~/Desktop/Formatted_Workbooks/")
    print(f"\nEnd Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
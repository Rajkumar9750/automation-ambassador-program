#!/usr/bin/env python3
"""
Dashboard Size Modifier for Tableau Workbooks
Modifies dashboard sizing properties including width, height, and sizing mode
"""

import zipfile
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from typing import Dict, Optional


class DashboardSizeModifier:
    """Modifies dashboard sizes in Tableau workbooks (.twbx files)"""
    
    # XML namespace
    NAMESPACE = 'http://tableauspec.com/xml'
    
    def __init__(self, twbx_path: str):
        """Initialize with path to TWBX file"""
        self.twbx_path = twbx_path
        self.temp_dir = None
        self.workbook_file = None
        
    def extract_workbook(self) -> str:
        """Extract the TWBX file and return path to workbook XML"""
        self.temp_dir = tempfile.mkdtemp()
        
        with zipfile.ZipFile(self.twbx_path, 'r') as zip_ref:
            zip_ref.extractall(self.temp_dir)
        
        # Find the .twb file
        for root, dirs, files in os.walk(self.temp_dir):
            for file in files:
                if file.endswith('.twb'):
                    self.workbook_file = os.path.join(root, file)
                    return self.workbook_file
        
        raise FileNotFoundError("No .twb file found in the workbook")
    
    def modify_dashboard_sizes(self, config: Dict[str, str]) -> int:
        """
        Modify dashboard sizes based on configuration
        
        Args:
            config: Dictionary with keys:
                - width: Dashboard width in pixels (e.g., "1366")
                - height: Dashboard height in pixels (e.g., "1000")
                - sizing_mode: Sizing mode (e.g., "fixed")
        
        Returns:
            Number of dashboards modified
        """
        if not self.workbook_file:
            raise ValueError("Workbook not extracted. Call extract_workbook() first")
        
        # Register namespace to preserve prefixes
        ET.register_namespace('', self.NAMESPACE)
        ET.register_namespace('table', self.NAMESPACE)
        
        tree = ET.parse(self.workbook_file)
        root = tree.getroot()
        
        # Extract configuration
        width = config.get('width', '1366')
        height = config.get('height', '1000')
        sizing_mode = config.get('sizing_mode', 'fixed')
        
        modified_count = 0
        
        # Find all dashboards
        dashboards = root.findall('.//{' + self.NAMESPACE + '}dashboard')
        if not dashboards:
            # Try without namespace
            dashboards = root.findall('.//dashboard')
        
        for dashboard in dashboards:
            # Add sizing attributes directly to dashboard element (valid Tableau attributes)
            # Instead of creating an invalid size sub-element
            dashboard.set('width', width)
            dashboard.set('height', height)
            
            # Set fixed-size mode if using fixed sizing
            if sizing_mode == 'fixed':
                dashboard.set('fixed-size', 'true')
            
            # Remove any invalid size elements that might exist
            size_elem = dashboard.find('{' + self.NAMESPACE + '}size')
            if size_elem is None:
                size_elem = dashboard.find('size')
            if size_elem is not None:
                dashboard.remove(size_elem)
            
            modified_count += 1
        
        # Save the modified XML
        tree.write(self.workbook_file, encoding='utf-8', xml_declaration=True)
        
        return modified_count
    
    def save_workbook(self, output_path: str) -> None:
        """Save the modified workbook to output path"""
        if not self.temp_dir:
            raise ValueError("No temporary directory. Extract workbook first.")
        
        # Create a new zip file with modified content
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, self.temp_dir)
                    zipf.write(file_path, arcname)
    
    def cleanup(self) -> None:
        """Clean up temporary files"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def apply_modifications(self, config: Dict[str, str]) -> tuple:
        """
        Complete workflow: extract, modify, and prepare for saving
        
        Args:
            config: Configuration dictionary
        
        Returns:
            Tuple of (modified_count, output_prepared)
        """
        self.extract_workbook()
        modified_count = self.modify_dashboard_sizes(config)
        return modified_count, True
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup"""
        self.cleanup()

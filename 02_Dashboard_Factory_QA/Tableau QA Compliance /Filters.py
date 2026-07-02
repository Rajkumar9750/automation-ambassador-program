import xml.etree.ElementTree as ET
import argparse
import os
import shutil
import zipfile
import tempfile
import glob
from datetime import datetime
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    HAS_TKINTER = True
except ImportError:
    HAS_TKINTER = False

class TableauFormatter:
    def __init__(self, file_path):
        """Initialize with the path to the Tableau workbook file."""
        self.file_path = file_path
        self.tree = None
        self.root = None
        self.backup_created = False
        self.is_twbx = file_path.lower().endswith('.twbx')
        self.temp_dir = None
        self.twb_path = file_path  # For .twb files, this is the same as file_path
        
        if self.is_twbx:
            self.extract_twbx()
        
    def extract_twbx(self):
        """Extract .twbx file to get the .twb file inside."""
        try:
            self.temp_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(self.file_path, 'r') as zip_ref:
                zip_ref.extractall(self.temp_dir)
            
            # Find the .twb file in the extracted contents
            for root, dirs, files in os.walk(self.temp_dir):
                for file in files:
                    if file.endswith('.twb'):
                        self.twb_path = os.path.join(root, file)
                        print(f"✅ Extracted .twb file: {file}")
                        return
            
            raise FileNotFoundError("No .twb file found in the .twbx archive")
            
        except Exception as e:
            print(f"❌ Error extracting .twbx file: {e}")
            if self.temp_dir:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            raise
        
    def create_backup(self):
        """Create a backup of the original file."""
        # Backup disabled - only generate final .twbx file
        if not self.backup_created:
            self.backup_created = True
    
    
    def load_workbook(self):
        """Load the Tableau workbook XML."""
        try:
            self.tree = ET.parse(self.twb_path)
            self.root = self.tree.getroot()
            print(f"✅ Loaded workbook: {os.path.basename(self.twb_path)}")
            return True
        except Exception as e:
            print(f"❌ Error loading workbook: {e}")
            return False
    
    def find_style_section(self):
        """Find or create the style section in the XML."""
        style_element = self.root.find('style')
        if style_element is None:
            # Create style section if it doesn't exist
            style_element = ET.SubElement(self.root, 'style')
            print("📝 Created new style section")
        return style_element
    
    def create_style_rule(self, parent, element_name, formats):
        """Create a style rule with the specified formats."""
        # Remove any existing style rules for this element in this parent
        existing_rules = parent.findall(f".//style-rule[@element='{element_name}']")
        for existing_rule in existing_rules:
            parent.remove(existing_rule)
        
        # Create new style rule
        style_rule = ET.SubElement(parent, 'style-rule')
        style_rule.set('element', element_name)
        
        for attr, value in formats.items():
            format_elem = ET.SubElement(style_rule, 'format')
            format_elem.set('attr', attr)
            format_elem.set('value', value)
    
    def apply_formatting(self, formatting_config):
        """Apply the specified formatting configuration to all style sections."""
        self.create_backup()
        
        if not self.load_workbook():
            return False
        
        # Valid Tableau filter/parameter element types
        VALID_ELEMENTS = {
            'quick-filter-title',
            'quick-filter',
            'parameter-ctrl-title',
            'parameter-ctrl'
        }
        
        # Find ALL style sections in the workbook (not just the top-level one)
        all_style_sections = self.root.findall('.//style')
        
        if not all_style_sections:
            print("⚠️  No style sections found, creating one...")
            all_style_sections = [self.find_style_section()]
        
        # Apply formatting for each element type to ALL style sections
        for element_type, formats in formatting_config.items():
            # Skip invalid elements (like 'dashboard-titles' which is handled separately)
            if element_type not in VALID_ELEMENTS:
                print(f"⚠️  Skipping invalid element type: {element_type}")
                continue
                
            if formats:  # Only apply if formats are specified
                for style_section in all_style_sections:
                    self.create_style_rule(style_section, element_type, formats)
                print(f"✅ Applied formatting to {element_type} ({len(all_style_sections)} style sections)")
        
        return True
    
    def save_workbook(self):
        """Save the modified workbook to a new folder with the workbook name."""
        try:
            # Create output folder with workbook name (without extension)
            workbook_name = os.path.splitext(os.path.basename(self.file_path))[0]
            output_dir = os.path.join(os.path.dirname(self.file_path), workbook_name)
            os.makedirs(output_dir, exist_ok=True)
            print(f"📁 Created output folder: {workbook_name}/")
            
            # Save the .twb file to the output directory with proper XML formatting
            output_twb_path = os.path.join(output_dir, os.path.basename(self.twb_path))
            
            # Write XML with proper encoding and declaration
            # Add proper indentation for readability and validation
            self._indent_xml(self.root)
            self.tree.write(
                output_twb_path,
                encoding='utf-8',
                xml_declaration=True,
                default_namespace=None
            )
            
            # Verify file was written correctly
            if not os.path.exists(output_twb_path) or os.path.getsize(output_twb_path) == 0:
                raise IOError(f"Failed to write .twb file: {output_twb_path}")
            
            print(f"✅ Saved .twb file: {workbook_name}/{os.path.basename(output_twb_path)}")
            
            # If it's a .twbx file, repackage it to the output directory
            if self.is_twbx:
                # Update temp_dir to point to output_dir for proper repackaging
                self.repackage_twbx(output_dir, output_twb_path)
            
            return True
        except Exception as e:
            print(f"❌ Error saving workbook: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _indent_xml(self, elem, level=0):
        """Add proper indentation to XML for readability and validation."""
        indent = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = indent + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = indent
            for child in elem:
                self._indent_xml(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = indent
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = indent
    
    def repackage_twbx(self, output_dir, modified_twb_path):
        """Repackage the modified .twb back into .twbx format in the output directory."""
        temp_twbx = None
        try:
            workbook_name = os.path.splitext(os.path.basename(self.file_path))[0]
            output_twbx_path = os.path.join(output_dir, f"{workbook_name}.twbx")
            temp_twbx = output_twbx_path + ".tmp"
            
            # Safe approach: Create a new TWBX by copying original and updating only the .twb file
            with zipfile.ZipFile(temp_twbx, 'w', zipfile.ZIP_DEFLATED) as zip_new:
                # Read original TWBX
                with zipfile.ZipFile(self.file_path, 'r') as original_zip:
                    # Copy all files except the .twb file, preserving structure
                    for item in original_zip.infolist():
                        if not item.filename.lower().endswith('.twb'):
                            data = original_zip.read(item.filename)
                            # Preserve file info to maintain structure
                            zip_new.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED)
                
                # Add the modified .twb file with proper handling
                arcname = os.path.basename(modified_twb_path)
                with open(modified_twb_path, 'rb') as f:
                    twb_data = f.read()
                    zip_new.writestr(arcname, twb_data, compress_type=zipfile.ZIP_DEFLATED)
            
            # Verify the temp file is valid before replacing
            try:
                with zipfile.ZipFile(temp_twbx, 'r') as verify_zip:
                    verify_zip.testzip()  # Returns None if all files are OK
            except Exception as verify_error:
                print(f"❌ Created .twbx file is corrupted: {verify_error}")
                if os.path.exists(temp_twbx):
                    os.remove(temp_twbx)
                raise verify_error
            
            # Replace original with temp file
            if os.path.exists(output_twbx_path):
                os.remove(output_twbx_path)
            os.rename(temp_twbx, output_twbx_path)
            
            print(f"✅ Repackaged .twbx file: {workbook_name}/{os.path.basename(output_twbx_path)}")
            
        except Exception as e:
            print(f"❌ Error repackaging .twbx file: {e}")
            import traceback
            traceback.print_exc()
            if temp_twbx and os.path.exists(temp_twbx):
                try:
                    os.remove(temp_twbx)
                except:
                    pass
        finally:
            # Clean up temporary directory
            if self.temp_dir:
                try:
                    shutil.rmtree(self.temp_dir, ignore_errors=True)
                except:
                    pass
    
    def __del__(self):
        """Cleanup temporary directory when object is destroyed."""
        if hasattr(self, 'temp_dir') and self.temp_dir:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def show_current_styles(self):
        """Display current styling for filters and parameters."""
        if not self.load_workbook():
            return
        
        style_section = self.root.find('style')
        if style_section is None:
            print("📋 No style section found in workbook")
            return
        
        target_elements = ['quick-filter-title', 'quick-filter', 'parameter-ctrl-title', 'parameter-ctrl']
        
        print("\n📋 Current Styles:")
        print("=" * 50)
        
        for element_name in target_elements:
            rule = style_section.find(f".//style-rule[@element='{element_name}']")
            if rule is not None:
                print(f"\n🎨 {element_name}:")
                formats = rule.findall('format')
                for fmt in formats:
                    attr = fmt.get('attr')
                    value = fmt.get('value')
                    print(f"   {attr}: {value}")
            else:
                print(f"\n❌ {element_name}: No styling found")

def get_default_cbre_config():
    """
    📝 EDIT THIS FUNCTION TO CUSTOMIZE FORMATTING
    
    Return default CBRE styling configuration for filters and parameters.
    
    Tableau element names:
    - quick-filter-title: Title of filter controls
    - quick-filter: Body/dropdown of filter controls
    - parameter-ctrl-title: Title of parameter controls
    - parameter-ctrl: Body/dropdown of parameter controls
    
    Available attributes:
    - color: Text color (hex code like #003f2d)
    - font-family: Font name (like Calibre, Arial, etc.)
    - font-size: Font size in points (like 10, 12, 14)
    - font-weight: bold, normal
    - background-color: Background color (hex code like #ffffff)
    - border-color: Border color (hex code like #cad1d3)
    """
    return {
        'quick-filter-title': {
            'color': "#435254",
            'font-family': 'Calibre',
            'font-size': '11'
        },
        'quick-filter': {
            'color': "#000000",
            'font-family': 'Calibre',
            'font-size': '11'
        },
        'parameter-ctrl-title': {
            'color': "#435254",
            'font-family': 'Calibre',
            'font-size': '11'
        },
        'parameter-ctrl': {
            'color': "#000000",
            'font-family': 'Calibre',
            'font-size': '11'
        }
    }

def get_custom_config():
    """Interactive function to get custom formatting configuration."""
    print("\n🎨 Custom Formatting Configuration")
    print("=" * 40)
    print("Enter values for each property (press Enter to skip):")
    
    config = {}
    elements = ['filter-title', 'filter-body', 'parameter-title', 'parameter-body']
    properties = ['color', 'font-family', 'font-size', 'font-weight', 'background-color', 'border-color']
    
    for element in elements:
        print(f"\n�� Configuring {element}:")
        element_config = {}
        
        for prop in properties:
            if prop == 'font-weight' and 'body' in element:
                continue  # Skip font-weight for body elements
            if prop == 'border-color' and 'title' in element:
                continue  # Skip border-color for title elements
                
            value = input(f"  {prop}: ").strip()
            if value:
                element_config[prop] = value
        
        if element_config:
            config[element] = element_config
    
    return config

def select_file():
    """Open a file picker dialog to select a Tableau workbook file."""
    if HAS_TKINTER:
        return select_file_gui()
    else:
        return select_file_cli()

def select_file_gui():
    """Use GUI file picker (tkinter)."""
    # Hide the root tkinter window
    root = tk.Tk()
    root.withdraw()
    
    # Configure file dialog
    file_types = [
        ("Tableau Workbooks", "*.twbx *.twb"),
        ("Tableau Packaged Workbooks", "*.twbx"),
        ("Tableau Workbooks", "*.twb"),
        ("All files", "*.*")
    ]
    
    try:
        file_path = filedialog.askopenfilename(
            title="Select Tableau Workbook",
            filetypes=file_types,
            initialdir=os.path.expanduser("~/Desktop")
        )
        
        if file_path:
            print(f"📂 Selected file: {file_path}")
            return file_path
        else:
            print("❌ No file selected")
            return None
            
    except Exception as e:
        print(f"❌ Error opening file dialog: {e}")
        return None
    finally:
        root.destroy()

def select_file_cli():
    """Use command-line file picker when GUI isn't available."""
    print("\n📁 Command-line File Browser")
    print("=" * 40)
    
    # Start from current directory or Desktop
    search_dirs = [
        os.getcwd(),
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~")
    ]
    
    print("🔍 Searching for Tableau files in:")
    for dir_path in search_dirs:
        if os.path.exists(dir_path):
            print(f"   📂 {dir_path}")
        else:
            print(f"   ❌ {dir_path} (not found)")
    
    # Look for Tableau files in common directories
    tableau_files = []
    for search_dir in search_dirs:
        if os.path.exists(search_dir):
            print(f"\n🔍 Scanning: {search_dir}")
            try:
                # Search for .twb files
                twb_pattern = os.path.join(search_dir, "**", "*.twb")
                twb_files = glob.glob(twb_pattern, recursive=True)
                print(f"   Found {len(twb_files)} .twb files")
                
                # Search for .twbx files
                twbx_pattern = os.path.join(search_dir, "**", "*.twbx")
                twbx_files = glob.glob(twbx_pattern, recursive=True)
                print(f"   Found {len(twbx_files)} .twbx files")
                
                tableau_files.extend(twb_files + twbx_files)
                
            except Exception as e:
                print(f"   ❌ Error scanning {search_dir}: {e}")
    
    # Remove duplicates and sort
    tableau_files = sorted(list(set(tableau_files)))
    
    print(f"\n📊 Total files found: {len(tableau_files)}")
    
    if not tableau_files:
        print("\n❌ No Tableau workbook files (.twb/.twbx) found in searched directories.")
        print("\n💡 Let's try a different approach:")
        
        # Try current directory only (non-recursive)
        current_dir = os.getcwd()
        print(f"\n🔍 Looking in current directory: {current_dir}")
        local_twb = glob.glob("*.twb")
        local_twbx = glob.glob("*.twbx")
        local_files = local_twb + local_twbx
        
        if local_files:
            print(f"Found {len(local_files)} files in current directory:")
            for f in local_files:
                print(f"   📄 {f}")
            tableau_files = [os.path.abspath(f) for f in local_files]
        else:
            print("   No Tableau files found in current directory either.")
            
            # List all files in current directory for debugging
            try:
                all_files = [f for f in os.listdir('.') if os.path.isfile(f)]
                print(f"\n📋 All files in current directory ({len(all_files)} total):")
                for f in all_files[:10]:  # Show first 10 files
                    print(f"   �� {f}")
                if len(all_files) > 10:
                    print(f"   ... and {len(all_files) - 10} more files")
            except Exception as e:
                print(f"   ❌ Error listing directory: {e}")
        
        if not tableau_files:
            print("\n📁 Please specify the file path manually:")
            manual_path = input("📁 Enter full path to your Tableau file: ").strip()
            if manual_path:
                # Handle quoted paths
                manual_path = manual_path.strip('"').strip("'")
                if os.path.exists(manual_path):
                    return manual_path
                else:
                    print(f"❌ File not found: {manual_path}")
                    return None
            else:
                print("❌ No path provided.")
                return None
    
    print(f"\nFound {len(tableau_files)} Tableau workbook(s):")
    print("-" * 40)
    
    for i, file_path in enumerate(tableau_files, 1):
        try:
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024 * 1024)
            rel_path = os.path.relpath(file_path)
            print(f"{i:2d}. {os.path.basename(file_path)} ({file_size_mb:.1f} MB)")
            print(f"    📂 {rel_path}")
        except Exception as e:
            print(f"{i:2d}. {os.path.basename(file_path)} (size unknown)")
            print(f"    📂 {file_path}")
    
    print(f"{len(tableau_files) + 1:2d}. 📁 Enter custom path")
    print(f"{len(tableau_files) + 2:2d}. ❌ Exit")
    
    while True:
        try:
            choice = input(f"\n�� Select file (1-{len(tableau_files) + 2}): ").strip()
            
            if not choice:
                continue
                
            choice_num = int(choice)
            
            if 1 <= choice_num <= len(tableau_files):
                selected_file = tableau_files[choice_num - 1]
                print(f"📂 Selected: {os.path.basename(selected_file)}")
                return selected_file
            elif choice_num == len(tableau_files) + 1:
                manual_path = input("📁 Enter full path to your Tableau file: ").strip()
                manual_path = manual_path.strip('"').strip("'")  # Remove quotes
                if manual_path and os.path.exists(manual_path):
                    return manual_path
                else:
                    print("❌ File not found. Please try again.")
            elif choice_num == len(tableau_files) + 2:
                print("❌ Exiting file selection.")
                return None
            else:
                print(f"❌ Please enter a number between 1 and {len(tableau_files) + 2}")
                
        except ValueError:
            print("❌ Please enter a valid number.")
        except KeyboardInterrupt:
            print("\n❌ File selection cancelled.")
            return None

def main():
    print("\n" + "=" * 50)
    print("🎨 Tableau Workbook Formatter")
    print("=" * 50)
    print("This script will apply professional formatting to your")
    print("Tableau workbook filters and parameters.\n")
    
    # Prompt user for file
    print("📁 Please select the Tableau workbook file to modify:")
    print("-" * 50)
    
    file_path = input("📁 Enter the path to your Tableau workbook (.twb or .twbx): ").strip()
    
    if not file_path:
        print("❌ No file path provided. Exiting.")
        return 1
    
    # Remove surrounding quotes if present
    file_path = file_path.strip('"').strip("'")
    
    # Validate file exists
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return 1
    
    # Validate file extension
    if not (file_path.lower().endswith('.twb') or file_path.lower().endswith('.twbx')):
        print(f"❌ File must be a Tableau workbook (.twb or .twbx) file")
        print(f"   Selected file: {file_path}")
        return 1
    
    print(f"✅ Working with: {os.path.basename(file_path)}")
    
    try:
        formatter = TableauFormatter(file_path)
    except Exception as e:
        print(f"❌ Error initializing formatter: {e}")
        return 1
    
    # Use CBRE preset formatting by default
    # 💡 To customize formatting: Edit the get_default_cbre_config() function below
    config = get_default_cbre_config()
    print("🎨 Applying CBRE formatting (edit get_default_cbre_config() function to customize)")
    
    # Apply formatting
    print(f"\n🚀 Applying formatting to: {os.path.basename(file_path)}")
    
    if formatter.apply_formatting(config) and formatter.save_workbook():
        print("\n🎉 Formatting applied successfully!")
        if file_path.lower().endswith('.twbx'):
            print("\nℹ️  Your .twbx file has been updated with new formatting.")
        print("\nℹ️  To see the changes:")
        print("1. Open the workbook in Tableau")
        print("2. Check the filters and parameters formatting")
        return 0
    else:
        print("\n❌ Failed to apply formatting")
        return 1

if __name__ == "__main__":
    exit(main())

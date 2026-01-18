"""
Flask API application for waste schedule data
"""
from flask import Flask, jsonify, request, render_template
from api.db import get_all_locations, get_location_schedule, get_schedule_group_schedule, search_locations
from scraper.fetcher import fetch_xlsx
from scraper.validator import validate_file_and_data
from scraper.db_writer import write_parsed_data
from pathlib import Path
import tempfile

app = Flask(__name__, 
            template_folder='../web/templates',
            static_folder='../web/static')

# Default URL for fetching
DEFAULT_XLSX_URL = "https://www.nemenkom.lt/uploads/failai/atliekos/Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikai/2026%20m-%20sausio-bir%C5%BEelio%20m%C4%97n%20%20Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikas.xlsx"

@app.route('/')
def index():
    """Main web page"""
    return render_template('index.html')

@app.route('/api/v1/locations', methods=['GET'])
def api_locations():
    """Get all locations"""
    query = request.args.get('q', '')
    
    if query:
        locations = search_locations(query)
    else:
        locations = get_all_locations()
    
    return jsonify({
        'locations': locations,
        'count': len(locations)
    })

@app.route('/api/v1/schedule', methods=['GET'])
def api_schedule():
    """Get schedule for a specific location"""
    location_id = request.args.get('location_id', type=int)
    village = request.args.get('village', '')
    street = request.args.get('street', '')
    
    if not location_id and not (village and street):
        return jsonify({
            'error': 'Must provide either location_id or both village and street'
        }), 400
    
    schedule = get_location_schedule(location_id=location_id, village=village, street=street)
    
    if not schedule:
        return jsonify({
            'error': 'Location not found'
        }), 404
    
    return jsonify(schedule)

@app.route('/api/v1/schedule-group/<schedule_group_id>', methods=['GET'])
def api_schedule_group(schedule_group_id):
    """Get schedule for a schedule group (hash-based ID)"""
    waste_type = request.args.get('waste_type', 'bendros')
    schedule = get_schedule_group_schedule(schedule_group_id, waste_type)
    return jsonify(schedule)

@app.route('/api/v1/data', methods=['POST'])
def api_post_data():
    """
    Accept scraped data from fetcher module
    Can either:
    1. POST with URL to fetch and process
    2. POST with raw xlsx file
    """
    if 'url' in request.json:
        # Fetch from URL
        url = request.json['url']
        year = request.json.get('year', 2026)
        
        try:
            # Fetch file
            file_path = fetch_xlsx(url)
            
            # Validate and parse
            is_valid, errors, parsed_data = validate_file_and_data(file_path, year)
            
            # Write to database
            success = write_parsed_data(parsed_data, url, errors if not is_valid else None)
            
            # Clean up temp file
            if file_path.exists() and str(file_path).startswith(tempfile.gettempdir()):
                file_path.unlink()
            
            if success:
                return jsonify({
                    'status': 'success',
                    'locations_processed': len(parsed_data)
                })
            else:
                return jsonify({
                    'status': 'error',
                    'errors': errors
                }), 400
                
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    elif 'file' in request.files:
        # Upload file directly
        file = request.files['file']
        year = request.form.get('year', 2026, type=int)
        
        # Save to temp file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
        file.save(temp_file.name)
        file_path = Path(temp_file.name)
        temp_file.close()
        
        try:
            # Validate and parse
            is_valid, errors, parsed_data = validate_file_and_data(file_path, year)
            
            # Write to database
            source_url = f"uploaded_file_{file.filename}"
            success = write_parsed_data(parsed_data, source_url, errors if not is_valid else None)
            
            # Clean up temp file
            file_path.unlink()
            
            if success:
                return jsonify({
                    'status': 'success',
                    'locations_processed': len(parsed_data)
                })
            else:
                return jsonify({
                    'status': 'error',
                    'errors': errors
                }), 400
                
        except Exception as e:
            if file_path.exists():
                file_path.unlink()
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    else:
        return jsonify({
            'error': 'Must provide either "url" in JSON or "file" in form data'
        }), 400

if __name__ == '__main__':
    # Initialize database if needed
    from database.init import init_database
    init_database()
    
    app.run(host='0.0.0.0', port=3333, debug=True)

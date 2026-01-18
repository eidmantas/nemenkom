"""
Flask API application for waste schedule data
"""
from flask import Flask, jsonify, request, render_template
from api.db import (
    get_all_locations, get_location_schedule, get_schedule_group_schedule, search_locations,
    get_unique_villages, get_streets_for_village, get_house_numbers_for_street, get_location_by_selection,
    village_has_streets, street_has_house_numbers
)

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
    street = request.args.get('street', None)  # None if not provided, '' if empty string provided
    house_numbers = request.args.get('house_numbers', None)  # None if not provided
    
    if location_id:
        schedule = get_location_schedule(location_id=location_id)
    elif village:
        # Validate based on what exists in database:
        # 1. If village has streets, street parameter must be provided
        # 2. If street has house numbers, house_numbers parameter must be provided
        
        if village_has_streets(village):
            # Village has streets, so street must be provided
            if street is None:
                return jsonify({
                    'error': 'This village has streets. Please select a street.'
                }), 400
            street_value = street
        else:
            # Village has no streets, use empty string
            street_value = ''
        
        # Check if street has house numbers
        if street_has_house_numbers(village, street_value):
            # Street has house numbers, so house_numbers must be provided
            if house_numbers is None:
                return jsonify({
                    'error': 'This street has specific house numbers. Please select a house number.'
                }), 400
        
        location = get_location_by_selection(village, street_value, house_numbers)
        if location:
            schedule = get_location_schedule(location_id=location['id'])
        else:
            schedule = None
    else:
        return jsonify({
            'error': 'Must provide either location_id or village'
        }), 400
    
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

@app.route('/api/v1/villages', methods=['GET'])
def api_villages():
    """Get list of unique villages"""
    villages = get_unique_villages()
    return jsonify({'villages': villages})

@app.route('/api/v1/streets', methods=['GET'])
def api_streets():
    """Get list of streets for a village"""
    village = request.args.get('village', '')
    if not village:
        return jsonify({'error': 'village parameter required'}), 400
    
    streets = get_streets_for_village(village)
    return jsonify({'streets': streets})

@app.route('/api/v1/house-numbers', methods=['GET'])
def api_house_numbers():
    """Get list of house numbers for a street"""
    village = request.args.get('village', '')
    street = request.args.get('street', '')
    
    if not village:
        return jsonify({'error': 'village parameter required'}), 400
    
    # street can be empty string for whole village
    house_numbers = get_house_numbers_for_street(village, street or '')
    return jsonify({'house_numbers': house_numbers})

if __name__ == '__main__':
    # Initialize database if needed
    from database.init import init_database
    init_database()
    
    app.run(host='0.0.0.0', port=3333, debug=True)

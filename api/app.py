"""
Flask API application for waste schedule data
"""
from flask import Flask, jsonify, request, render_template, redirect
from flasgger import Swagger
from functools import wraps
from api.db import (
    get_all_locations, get_location_schedule, get_schedule_group_schedule, search_locations,
    get_unique_villages, get_streets_for_village, get_house_numbers_for_street, get_location_by_selection,
    village_has_streets, street_has_house_numbers
)
from api.google_calendar import (
    create_calendar_for_schedule_group, get_existing_calendar_info,
    list_available_calendars, generate_calendar_subscription_link
)
import config

def require_api_key(f):
    """
    Decorator to require API key authentication for protected endpoints
    Automatically handles API key checking with helpful error messages
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check multiple possible locations for API key
        api_key = (
            request.headers.get(config.API_KEY_HEADER) or
            request.args.get('api_key')  # Also allow in query params
        )

        if not api_key or api_key != config.API_KEY:
            return jsonify({
                'error': 'Authentication required',
                'details': f'Please provide a valid API key in {config.API_KEY_HEADER} header or api_key parameter',
                'example': f'curl -H "{config.API_KEY_HEADER}: YOUR_API_KEY" http://localhost:3333/api/v1/endpoint'
            }), 401

        return f(*args, **kwargs)
    return decorated_function

app = Flask(__name__, 
            template_folder='../web/templates',
            static_folder='../web/static')

# Initialize Swagger
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api-docs"
}

swagger_template = {
    "swagger": "2.0",
    "info": {
        "title": "Waste Schedule API",
        "description": "REST API for waste collection schedules. All endpoints are read-only (GET only).",
        "version": "1.0.0"
    },
    "host": "localhost:3333",
    "basePath": "/api/v1",
    "schemes": ["http"],
    "securityDefinitions": {},
}

swagger = Swagger(app, config=swagger_config, template=swagger_template)

# Default URL for fetching
DEFAULT_XLSX_URL = "https://www.nemenkom.lt/uploads/failai/atliekos/Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikai/2026%20m-%20sausio-bir%C5%BEelio%20m%C4%97n%20%20Buitini%C5%B3%20atliek%C5%B3%20surinkimo%20grafikas.xlsx"

# Security: Only allow GET methods for API endpoints
@app.before_request
def only_get_allowed():
    """Reject all non-GET requests for security"""
    if request.method != 'GET' and request.path.startswith('/api/'):
        return jsonify({'error': 'Only GET method is allowed'}), 405

@app.route('/')
def index():
    """Main web page"""
    return render_template('index.html')

@app.route('/api-docs')
def api_docs():
    """Redirect to Swagger UI"""
    return redirect('/api-docs/index.html')

@app.route('/api/v1/locations', methods=['GET'])
def api_locations():
    """
    Get all locations or search locations
    ---
    tags:
      - Locations
    parameters:
      - name: q
        in: query
        type: string
        required: false
        description: Search query (searches in seniūnija, village, and street names)
    responses:
      200:
        description: List of locations
        schema:
          type: object
          properties:
            locations:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  seniūnija:
                    type: string
                  village:
                    type: string
                  street:
                    type: string
                  house_numbers:
                    type: string
                    nullable: true
                  kaimai_hash:
                    type: string
            count:
              type: integer
    """
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
    """
    Get schedule for a specific location
    ---
    tags:
      - Schedule
    parameters:
      - name: location_id
        in: query
        type: integer
        required: false
        description: Location ID (alternative to seniūnija/village/street)
      - name: seniūnija
        in: query
        type: string
        required: false
        description: Seniūnija name (required if no location_id)
      - name: village
        in: query
        type: string
        required: false
        description: Village name (required if no location_id)
      - name: street
        in: query
        type: string
        required: false
        description: Street name (required if village has streets)
      - name: house_numbers
        in: query
        type: string
        required: false
        description: House numbers (required if street has specific house numbers)
    responses:
      200:
        description: Schedule data
        schema:
          type: object
          properties:
            id:
              type: integer
            seniūnija:
              type: string
            village:
              type: string
            street:
              type: string
            house_numbers:
              type: string
              nullable: true
            kaimai_hash:
              type: string
            schedule_group_id:
              type: string
            waste_type:
              type: string
            dates:
              type: array
              items:
                type: object
                properties:
                  date:
                    type: string
                    format: date
                  waste_type:
                    type: string
      400:
        description: Bad request (missing required parameters)
      404:
        description: Location not found
    """
    location_id = request.args.get('location_id', type=int)
    seniūnija = request.args.get('seniūnija', '')
    village = request.args.get('village', '')
    street = request.args.get('street', None)  # None if not provided, '' if empty string provided
    house_numbers = request.args.get('house_numbers', None)  # None if not provided
    
    if location_id:
        schedule = get_location_schedule(location_id=location_id)
    elif seniūnija and village:
        
        # Validate based on what exists in database:
        # 1. If village has streets, street parameter must be provided
        # 2. If street has house numbers, house_numbers parameter must be provided
        
        if village_has_streets(seniūnija, village):
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
        if street_has_house_numbers(seniūnija, village, street_value):
            # Street has house numbers, so house_numbers must be provided
            if house_numbers is None:
                return jsonify({
                    'error': 'This street has specific house numbers. Please select a house number.'
                }), 400
        
        location = get_location_by_selection(seniūnija, village, street_value, house_numbers)
        if location:
            schedule = get_location_schedule(location_id=location['id'])
        else:
            schedule = None
    else:
        return jsonify({
            'error': 'Must provide either location_id or both seniūnija and village'
        }), 400
    
    if not schedule:
        return jsonify({
            'error': 'Location not found'
        }), 404
    
    return jsonify(schedule)

@app.route('/api/v1/schedule-group/<schedule_group_id>', methods=['GET'])
def api_schedule_group(schedule_group_id):
    """
    Get schedule for a schedule group (hash-based ID)
    ---
    tags:
      - Schedule
    parameters:
      - name: schedule_group_id
        in: path
        type: string
        required: true
        description: Schedule group ID (hash-based, e.g., "sg_abc123")
      - name: waste_type
        in: query
        type: string
        required: false
        default: bendros
        description: Waste type (bendros, plastikas, stiklas, etc.)
    responses:
      200:
        description: Schedule group data
        schema:
          type: object
          properties:
            schedule_group_id:
              type: string
            metadata:
              type: object
            location_count:
              type: integer
            locations:
              type: array
            dates:
              type: array
      404:
        description: Schedule group not found
    """
    waste_type = request.args.get('waste_type', 'bendros')
    schedule = get_schedule_group_schedule(schedule_group_id, waste_type)
    return jsonify(schedule)

@app.route('/api/v1/villages', methods=['GET'])
def api_villages():
    """
    Get list of unique villages with their seniūnija
    ---
    tags:
      - Locations
    responses:
      200:
        description: List of unique villages
        schema:
          type: object
          properties:
            villages:
              type: array
              items:
                type: object
                properties:
                  seniūnija:
                    type: string
                  village:
                    type: string
    """
    villages = get_unique_villages()
    return jsonify({'villages': villages})

@app.route('/api/v1/streets', methods=['GET'])
def api_streets():
    """
    Get list of streets for a village
    ---
    tags:
      - Locations
    parameters:
      - name: seniūnija
        in: query
        type: string
        required: true
        description: Seniūnija name
      - name: village
        in: query
        type: string
        required: true
        description: Village name
    responses:
      200:
        description: List of streets (empty string means "all village")
        schema:
          type: object
          properties:
            streets:
              type: array
              items:
                type: string
      400:
        description: Missing required parameters
    """
    seniūnija = request.args.get('seniūnija', '')
    village = request.args.get('village', '')
    
    if not seniūnija or not village:
        return jsonify({'error': 'seniūnija and village parameters required'}), 400
    
    streets = get_streets_for_village(seniūnija, village)
    return jsonify({'streets': streets})

@app.route('/api/v1/house-numbers', methods=['GET'])
def api_house_numbers():
    """
    Get list of house numbers for a street
    ---
    tags:
      - Locations
    parameters:
      - name: seniūnija
        in: query
        type: string
        required: true
        description: Seniūnija name
      - name: village
        in: query
        type: string
        required: true
        description: Village name
      - name: street
        in: query
        type: string
        required: false
        description: Street name (empty string for whole village)
    responses:
      200:
        description: List of house numbers (empty string means "all")
        schema:
          type: object
          properties:
            house_numbers:
              type: array
              items:
                type: string
      400:
        description: Missing required parameters
    """
    seniūnija = request.args.get('seniūnija', '')
    village = request.args.get('village', '')
    street = request.args.get('street', '')
    
    if not seniūnija or not village:
        return jsonify({'error': 'seniūnija and village parameters required'}), 400
    
    # street can be empty string for whole village
    house_numbers = get_house_numbers_for_street(seniūnija, village, street or '')
    return jsonify({'house_numbers': house_numbers})

@app.route('/api/v1/available-calendars', methods=['GET'])
@require_api_key
def api_available_calendars():
    """
    List all available Google Calendars
    ---
    tags:
      - Google Calendar
    parameters:
      - name: X-API-KEY
        in: header
        type: string
        required: true
        description: API key for authentication
    responses:
      200:
        description: List of available calendars
        schema:
          type: object
          properties:
            calendars:
              type: array
              items:
                type: object
                properties:
                  calendar_id:
                    type: string
                  calendar_name:
                    type: string
                  description:
                    type: string
                  subscription_link:
                    type: string
                  timeZone:
                    type: string
      401:
        description: Invalid or missing API key
    """
    calendars = list_available_calendars()
    return jsonify({'calendars': calendars})

@app.route('/api/v1/generate-calendar/<schedule_group_id>', methods=['GET'])
@require_api_key
def api_generate_calendar(schedule_group_id):
    """
    Generate Google Calendar for a schedule group
    ---
    tags:
      - Google Calendar
    parameters:
      - name: schedule_group_id
        in: path
        type: string
        required: true
        description: Schedule group ID to generate calendar for
      - name: location_name
        in: query
        type: string
        required: true
        description: Human-readable location name for calendar title
      - name: waste_type
        in: query
        type: string
        required: false
        default: bendros
        description: Waste type (bendros, plastikas, stiklas)
      - name: X-API-KEY
        in: header
        type: string
        required: true
        description: API key for authentication
    responses:
      200:
        description: Calendar created successfully
        schema:
          type: object
          properties:
            calendar_id:
              type: string
            calendar_name:
              type: string
            subscription_link:
              type: string
            events_created:
              type: integer
            success:
              type: boolean
      400:
        description: Missing required parameters
      401:
        description: Invalid or missing API key
      500:
        description: Calendar creation failed
    """
    location_name = request.args.get('location_name', '')
    waste_type = request.args.get('waste_type', 'bendros')

    if not location_name:
        return jsonify({'error': 'location_name parameter is required'}), 400

    # Get schedule group info to extract dates
    schedule_info = get_schedule_group_schedule(schedule_group_id, waste_type)
    if not schedule_info or 'dates' not in schedule_info:
        return jsonify({'error': 'Schedule group not found or has no dates'}), 404

    # Extract date strings from schedule
    date_strings = [date_info['date'] for date_info in schedule_info['dates']]

    # Generate calendar
    result = create_calendar_for_schedule_group(
        schedule_group_id=schedule_group_id,
        location_name=location_name,
        dates=date_strings,
        waste_type=waste_type
    )

    if not result:
        return jsonify({'error': 'Failed to create calendar'}), 500

    return jsonify(result)

@app.route('/api/v1/calendar-info/<calendar_id>', methods=['GET'])
@require_api_key
def api_calendar_info(calendar_id):
    """
    Get information about a specific calendar
    ---
    tags:
      - Google Calendar
    parameters:
      - name: calendar_id
        in: path
        type: string
        required: true
        description: Google Calendar ID
      - name: X-API-KEY
        in: header
        type: string
        required: true
        description: API key for authentication
    responses:
      200:
        description: Calendar information
        schema:
          type: object
          properties:
            calendar_id:
              type: string
            calendar_name:
              type: string
            description:
              type: string
            subscription_link:
              type: string
            timeZone:
              type: string
      401:
        description: Invalid or missing API key
      404:
        description: Calendar not found
    """
    calendar_info = get_existing_calendar_info(calendar_id)
    if not calendar_info:
        return jsonify({'error': 'Calendar not found'}), 404

    return jsonify(calendar_info)

if __name__ == '__main__':
    # Initialize database if needed
    from database.init import init_database
    init_database()
    
    app.run(host='0.0.0.0', port=3333, debug=True)

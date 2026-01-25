"""
Flask API application for waste schedule data
"""

import logging
from pathlib import Path

from flasgger import Swagger
from flask import Flask, jsonify, redirect, render_template, request

from services.api.db import (
    get_all_locations,
    get_house_numbers_for_street,
    get_location_by_selection,
    get_location_schedule,
    get_schedule_group_schedule,
    get_streets_for_village,
    get_unique_villages,
    search_locations,
    street_has_house_numbers,
    village_has_streets,
)
import config
from services.common.calendar_client import (
    generate_calendar_subscription_link,
    get_existing_calendar_info,
    list_available_calendars,
)
from services.common.logging_utils import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
app = Flask(
    __name__,
    template_folder=str(REPO_ROOT / "services" / "web" / "templates"),
    static_folder=str(REPO_ROOT / "services" / "web" / "static"),
)
app.config["DEBUG"] = config.DEBUG

# Initialize Swagger
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": "apispec",
            "route": "/apispec.json",
            "rule_filter": lambda _rule: True,
            "model_filter": lambda _tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api-docs",
}

swagger_template = {
    "swagger": "2.0",
    "info": {
        "title": "Waste Schedule API",
        "description": "REST API for waste collection schedules. All endpoints are read-only (GET only).",
        "version": "1.0.0",
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
    if request.method != "GET" and request.path.startswith("/api/"):
        return jsonify({"error": "Only GET method is allowed"}), 405


@app.route("/")
def index():
    """Main web page"""
    return render_template("index.html")


@app.route("/api-docs")
def api_docs():
    """Redirect to Swagger UI"""
    return redirect("/api-docs/index.html")


@app.route("/api/v1/locations", methods=["GET"])
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
        description: Search query (searches in seniunija, village, and street names)
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
                  seniunija:
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
    query = request.args.get("q", "")

    if query:
        locations = search_locations(query)
    else:
        locations = get_all_locations()

    return jsonify({"locations": locations, "count": len(locations)})


@app.route("/api/v1/schedule", methods=["GET"])
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
        description: Location ID (alternative to seniunija/village/street)
      - name: seniunija
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
            seniunija:
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
            calendar_id:
              type: string
              nullable: true
              description: Google Calendar ID (if calendar exists)
            subscription_link:
              type: string
              nullable: true
              description: Google Calendar subscription link (if calendar exists)
            calendar_status:
              type: object
              description: Calendar sync status
              properties:
                status:
                  type: string
                  enum: [synced, pending, needs_update, not_available]
                  description: Calendar status (synced=ready, pending=not created, needs_update=dates changed)
                calendar_id:
                  type: string
                  nullable: true
      400:
        description: Bad request (missing required parameters)
      404:
        description: Location not found
    """
    location_id = request.args.get("location_id", type=int)
    seniunija = request.args.get("seniunija", "")
    village = request.args.get("village", "")
    street = request.args.get(
        "street", None
    )  # None if not provided, '' if empty string provided
    house_numbers = request.args.get("house_numbers", None)  # None if not provided

    if location_id:
        schedule = get_location_schedule(location_id=location_id)
    elif seniunija and village:

        # Validate based on what exists in database:
        # 1. If village has streets, street parameter must be provided
        # 2. If street has house numbers, house_numbers parameter must be provided

        if village_has_streets(seniunija, village):
            # Village has streets, so street must be provided
            if street is None:
                return (
                    jsonify(
                        {"error": "This village has streets. Please select a street."}
                    ),
                    400,
                )
            street_value = street
        else:
            # Village has no streets, use empty string
            street_value = ""

        # Check if street has house numbers
        if street_has_house_numbers(seniunija, village, street_value):
            # Street has house numbers, so house_numbers must be provided
            if house_numbers is None:
                return (
                    jsonify(
                        {
                            "error": "This street has specific house numbers. Please select a house number."
                        }
                    ),
                    400,
                )

        location = get_location_by_selection(
            seniunija, village, street_value, house_numbers
        )
        if location:
            schedule = get_location_schedule(location_id=location["id"])
        else:
            schedule = None
    else:
        return (
            jsonify(
                {
                    "error": "Must provide either location_id or both seniunija and village"
                }
            ),
            400,
        )

    if not schedule:
        return jsonify({"error": "Location not found"}), 404

    return jsonify(schedule)


@app.route("/api/v1/schedule-group/<schedule_group_id>", methods=["GET"])
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
    waste_type = request.args.get("waste_type", "bendros")
    schedule = get_schedule_group_schedule(schedule_group_id, waste_type)

    # Add subscription_link if calendar_id exists
    if schedule.get("metadata", {}).get("calendar_id"):
        calendar_id = schedule["metadata"]["calendar_id"]
        schedule["subscription_link"] = generate_calendar_subscription_link(calendar_id)

    return jsonify(schedule)


@app.route("/api/v1/villages", methods=["GET"])
def api_villages():
    """
    Get list of unique villages with their seniunija
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
                  seniunija:
                    type: string
                  village:
                    type: string
    """
    villages = get_unique_villages()
    return jsonify({"villages": villages})


@app.route("/api/v1/streets", methods=["GET"])
def api_streets():
    """
    Get list of streets for a village
    ---
    tags:
      - Locations
    parameters:
      - name: seniunija
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
    seniunija = request.args.get("seniunija", "")
    village = request.args.get("village", "")

    if not seniunija or not village:
        return jsonify({"error": "seniunija and village parameters required"}), 400

    streets = get_streets_for_village(seniunija, village)
    return jsonify({"streets": streets})


@app.route("/api/v1/house-numbers", methods=["GET"])
def api_house_numbers():
    """
    Get list of house numbers for a street
    ---
    tags:
      - Locations
    parameters:
      - name: seniunija
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
    seniunija = request.args.get("seniunija", "")
    village = request.args.get("village", "")
    street = request.args.get("street", "")

    if not seniunija or not village:
        return jsonify({"error": "seniunija and village parameters required"}), 400

    # street can be empty string for whole village
    house_numbers = get_house_numbers_for_street(seniunija, village, street or "")
    return jsonify({"house_numbers": house_numbers})


@app.route("/api/v1/available-calendars", methods=["GET"])
def api_available_calendars():
    """
    List all available Google Calendars (GET - public)
    ---
    tags:
      - Google Calendar
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
    return jsonify({"calendars": calendars})


@app.route("/api/v1/calendar-info/<calendar_id>", methods=["GET"])
def api_calendar_info(calendar_id):
    """
    Get information about a specific calendar (GET - public)
    ---
    tags:
      - Google Calendar
    parameters:
      - name: calendar_id
        in: path
        type: string
        required: true
        description: Google Calendar ID
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
        return jsonify({"error": "Calendar not found"}), 404

    return jsonify(calendar_info)


if __name__ == "__main__":
    logger.info("Starting API server on 0.0.0.0:3333")
    app.run(host="0.0.0.0", port=3333, debug=config.DEBUG)

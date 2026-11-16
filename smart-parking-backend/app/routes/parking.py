"""
PARKING DISCOVERY  -  locations and live slot status   (SRS FR-04..FR-07 | SDD 10.1)

    GET /api/parking/locations   the parking facilities and how many slots are free now
    GET /api/parking/slots       the slot grid for a chosen place / date / time / duration

These two are public (no login) so visitors can look before registering.
"""
from flask import Blueprint, current_app, jsonify, request

from ..db import get_db
from ..serializers import slot_dict
from ..services import SLOT_SELECT, build_window, now_window, slot_effective_statuses
from ..utils import Validator, now_local, tz_suffix

bp = Blueprint("parking", __name__, url_prefix="/api/parking")


@bp.get("/locations")
def list_locations():
    db = get_db()
    slots = db.execute(SLOT_SELECT).fetchall()
    start, end = now_window()
    statuses = slot_effective_statuses(db, slots, start, end)

    # Group slots into location -> zone, counting totals and free slots.
    locations = {}
    for loc in db.execute("SELECT * FROM parking_locations ORDER BY location_id").fetchall():
        locations[loc["location_id"]] = {
            "location_id": loc["location_id"], "name": loc["name"], "address": loc["address"],
            "total_slots": 0, "available_slots": 0, "zones": {},
        }
    for slot in slots:
        loc = locations[slot["location_id"]]
        zone = loc["zones"].setdefault(slot["zone_id"], {
            "zone_id": slot["zone_id"], "zone_name": slot["zone_name"], "floor": slot["floor"],
            "total_slots": 0, "available_slots": 0,
        })
        free = statuses[slot["slot_id"]] == "AVAILABLE"
        for bucket in (loc, zone):
            bucket["total_slots"] += 1
            bucket["available_slots"] += int(free)

    result = []
    for loc in locations.values():
        loc["zones"] = list(loc["zones"].values())
        result.append(loc)
    return jsonify({"locations": result})


@bp.get("/slots")
def list_slots():
    """
    Query options (all optional):
        location_id, zone_id      which place
        date=2026-09-22           default: today
        start_time=19:00          default: right now
        duration_hours=2          default: 2
        vehicle_type=CAR|BIKE|EV  only this kind of slot
        status=AVAILABLE          only slots with this status
        q=covered                 search slot number / vehicle type / description
    """
    v = Validator(request.args)
    location_id = v.integer("location_id", "Location", minimum=1, required=False)
    zone_id = v.integer("zone_id", "Zone", minimum=1, required=False)
    day = v.date("date", "Date", required=False)
    start_time = v.time("start_time", "Start time", required=False)
    hours = v.integer("duration_hours", "Duration", minimum=1,
                      maximum=current_app.config["MAX_DURATION_HOURS"], required=False)
    vehicle_type = v.choice("vehicle_type", "Vehicle type", {"CAR", "BIKE", "EV"}, aliases={"EV_CAR": "EV"}, required=False)
    wanted_status = v.choice("status", "Status", {"AVAILABLE", "OCCUPIED", "RESERVED", "OUT_OF_SERVICE"}, required=False)
    search = v.text("q", "Search", required=False, max_len=40)
    v.done()

    now = now_local()
    start, end = build_window(day or now.date(), start_time or now.time().replace(second=0), hours or 2)

    sql, params = SLOT_SELECT + " WHERE 1 = 1", []
    for column, value in (("l.location_id", location_id), ("z.zone_id", zone_id), ("s.vehicle_type", vehicle_type)):
        if value is not None:
            sql += f" AND {column} = ?"
            params.append(value)
    if search:
        like = f"%{search}%"
        sql += " AND (s.slot_no LIKE ? OR s.vehicle_type LIKE ? OR s.description LIKE ?)"
        params += [like, like, like]
    sql += " ORDER BY l.location_id, z.zone_id, s.slot_id"

    db = get_db()
    rows = db.execute(sql, params).fetchall()
    statuses = slot_effective_statuses(db, rows, start, end)

    items = [slot_dict(r, statuses[r["slot_id"]]) for r in rows if not wanted_status or statuses[r["slot_id"]] == wanted_status]
    summary = {"total": len(items), "available": 0, "occupied": 0, "reserved": 0, "out_of_service": 0}
    for item in items:
        summary[item["status"].lower()] += 1

    return jsonify({
        "window": {"start_time": start.isoformat() + tz_suffix(), "end_time": end.isoformat() + tz_suffix(),
                   "duration_hours": int((end - start).total_seconds() // 3600)},
        "service_fee": current_app.config["SERVICE_FEE"],
        "summary": summary,
        "slots": items,
    })

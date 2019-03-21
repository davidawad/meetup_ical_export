import os
import json
import pytz
import requests
import icalendar

from icalendar import Calendar, Event
from datetime import datetime, timedelta
from flask import Flask, make_response


ICS_FILENAME = 'meetup.ics'
MEETUP_KEY = os.environ.get('MEETUP_KEY', None)
DEBUG = os.environ.get('DEBUG', False)

app = Flask(__name__)

# cached variable of icalendar string
ICAL_FEED = None
# timestamp of the last time we requested meetup
last_fetched = None

if DEBUG is not None:
    app.logger.warning('DEBUGGING ENABLED')


def fetch_groups():

    payload = {'key': MEETUP_KEY}
    r = requests.get('http://api.meetup.com/self/groups', params = payload)

    groups = None

    if r.status_code != 200:
        app.logger.warning('FAILED REQUEST ' + str(r) + r.text)

    groups_obj = json.loads(r.text)

    return groups_obj


def fetch_events(groups):

    events_obj = []

    for g in groups:
        groupname = g.get('urlname')

        payload = {'key': MEETUP_KEY}
        r = requests.get('http://api.meetup.com/' + groupname + '/events', params = payload)

        events = json.loads(r.text)

        for event in events:
            events_obj.append(event)

        # only take the first few events so we don't bother meetup too much :)
        if DEBUG: break

    return events_obj


def convert_event_obj_to_ical(e):
    # note : e is an event object

    ret = ''

    #  dict_keys(['created', 'duration', 'id', 'name', 'rsvp_limit',
            #  'date_in_series_pattern', 'status', 'time', 'local_date',
            #  'local_time', 'updated', 'utc_offset', 'waitlist_count',
            #  'yes_rsvp_count', 'venue', 'group', 'link', 'description', 'visibility'])

    # get our event details out of the meetup object
    time       = e.get('time')
    local_time = e.get('local_time')
    day        = e.get('local_date')
    venue      = e.get('venue')
    link       = e.get('link')

    # create address string for the event
    address_string = ', '.join([venue.get('address_1', ''), venue.get('city', ''), venue.get('state', ''), venue.get('zip', '')])
    address_string = address_string[0: len(address_string)]

    time_string = local_time + " " + day

    start_time_object = datetime.strptime(time_string, '%H:%M %Y-%m-%d')
    end_time_object = start_time_object + timedelta(hours=2)

    event = icalendar.Event()
    event.add('summary', e.get('name')) # 'summary' is the event title
    event.add('description', e.get('description') + '\n' + link)
    event.add('dtstart', start_time_object)
    event.add('dtend', end_time_object)
    event.add('location', address_string)

    ret = event
    return ret


def ical_convert(events):
    ret = ''
    cal = icalendar.Calendar()
    cal.add('prodid', '-//Meetup Events Export//mxm.dk//')
    cal.add('version', '2.0')

    for e in events:
        event = convert_event_obj_to_ical(e)
        cal.add_component(event)

    ical_string = cal.to_ical(sorted=False)
    ret = ical_string
    return ret


def fetch_feed():
    global ICAL_FEED
    global last_fetched

    # is our data over a day old?
    # assumes both meetups, and your life, are planned over a day in advance
    old_data = False if last_fetched is None else datetime.now() - timedelta(hours=24) >= last_fetched

    if ICAL_FEED is None or last_fetched is None or old_data :
        app.logger.warning("ICAL_FEED is either old, or nonexistent, fetching new data.")
        ICAL_FEED = ical_convert(fetch_events(fetch_groups()))
        last_fetched = datetime.now()

    else:
        app.logger.warning("ICAL_FEED is cached, returning cached copy")

    return ICAL_FEED


# health check
@app.route("/")
def hello():
        return "Hello World!"


@app.route('/calendar/')
def calendar():
    #  Get the calendar data
    #  turn calendar data into a response
    response = make_response(fetch_feed())
    response.headers["Content-Disposition"] = "attachment; filename="+ICS_FILENAME
    return response


# for quick local testing
#  if __name__ == "__main__":
    #  if not MEETUP_KEY: exit(3)
    #  ical_string = ical_convert(fetch_events(fetch_groups()))

    #  print(ical_string)


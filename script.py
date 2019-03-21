import os
import json
import pytz
import requests
import datetime
import icalendar



MEETUP_KEY = os.environ.get('MEETUP_KEY', None)



"""
event obj contains:
dict_keys(['created', 'duration', 'id', 'name', 'rsvp_limit',
            'date_in_series_pattern', 'status', 'time', 'local_date',
            'local_time', 'updated', 'utc_offset', 'waitlist_count',
            'yes_rsvp_count', 'venue', 'group', 'link', 'description', 'visibility'])
"""


def fetch_groups():

    payload = {'key': MEETUP_KEY}
    r = requests.get('http://api.meetup.com/self/groups', params = payload)

    groups = None

    if r.status_code != 200:
        print(r)
        exit(4)

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

    return events_obj


def convert_event_obj_to_ical(e):
    # note : e is an event object

    ret = ''

    #  print(cal)

#  dict_keys(['created', 'duration', 'id', 'name', 'rsvp_limit',
            #  'date_in_series_pattern', 'status', 'time', 'local_date',
            #  'local_time', 'updated', 'utc_offset', 'waitlist_count',
            #  'yes_rsvp_count', 'venue', 'group', 'link', 'description', 'visibility'])

    event = icalendar.Event()


    time = e.get('time')
    local_time = e.get('local_time')
    day = e.get('local_date')
    venue = e.get('venue')
    link = e.get('link')

    # 'address_1': '531 Cookman Ave', 'city': 'Asbury Park', 'country': 'us', 'localized_country_name': 'USA', 'zip': '07712', 'state': 'NJ'}
    address_string = ', '.join([venue.get('address_1', ''), venue.get('city', ''), venue.get('state', ''), venue.get('zip', '')])

    address_string = address_string[0: len(address_string)]
    #  print(e)
    #  print(time)
    #  print(day)
    print(address_string)


    time_string = local_time + " " + day
    print(time_string)

    start_time_object = datetime.datetime.strptime(time_string, '%H:%M %Y-%m-%d')

    end_time_object = start_time_object + datetime.timedelta(hours=2)


    # summary is title
    event.add('summary', e.get('name'))
    event.add('description', e.get('description') + '\n' + link)
    event.add('dtstart', start_time_object)
    event.add('dtend', end_time_object)
    event.add('location', end_time_object)
    #  event.add('dtstamp', datetime(2005,4,4,0,10,0,tzinfo=pytz.utc))

    return ret


def ical_convert(events):
    ret = ''
    cal = icalendar.Calendar()
    cal.add('prodid', '-//Meetup Events Export//mxm.dk//')
    cal.add('version', '2.0')

    for e in events:
        event = convert_event_obj_to_ical(e)
        cal.add_component(event)

    ical_string = cal.to_ical()
    ret = ical_string
    return ret




if __name__ == "__main__":
    if not MEETUP_KEY: exit(3)
    ical_string = ical_convert(fetch_events(fetch_groups()))

    print(ical_string)


# meetup_ical_export


This script will find all the meetup groups you're a part of, and take all of their events and export them in ical format so you can subscribe to a rolling calendar of meetup events that you might be interested in.

But now you don't have to go on meetup.com or say that you're going ahead of time. :)

## setup

### meetup api key
Just export your meetup API key as `MEETUP_KEY`.

### python depenencies
```
$ pip install -r requirements.txt
```

### run the script
```
$ python script.py
```



## Local Deployment

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/davidawad/meetup_ical_export)

As I understand it you should be able to deploy just by hitting this button!

Just make sure to set the Config Var `MEETUP_KEY` to your meetup api key.

###### You can get a meetup api key [here](https://secure.meetup.com/meetup_api/key/).




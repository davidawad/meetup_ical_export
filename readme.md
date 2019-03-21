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



### Deploying if you're not in EST

You'll need to do one extra step:

look for the timezone string `'America/New_York'` in `app.py`, and make sure you adjust it to **your local timezone string**.

If you're not sure what yours is just take a look at [this list](https://garygregory.wordpress.com/2013/06/18/what-are-the-java-timezone-ids/). I'm pretty confident almost all of them should be supported.


A coroutine based event tracker that simply writes to stdout/stderr.

![screenshot](https://github.com/melbaa/notify/blob/master/ss.png)

# Features
* check email at http://abv.bg
* notify when followed streamers on http://twitch.tv go live/offline
* notify about favourite players on http://twitch.tv/qlrankstv  
* it's easy to add an event tracker, just add another coroutine

# Why
Checking email manually gets tedious fast.
I wanted something to notify me about my email, without shoving pixels in
my face and without making annoying sounds. This application keeps my sanity
and doesn't break my concentration.

# Install
python 3.6  
pip install -r requirements.txt  

# Usage
* make a secrets.json by following the example, you can delete sections
you don't need
* python -m melbalabs.notify.notify secrets.json

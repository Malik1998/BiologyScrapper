# How to run the FLR scoring tool (Step 2)

This is the small test where two (or more) of us independently score the same
batch of photos, so we can check whether we actually agree. No coding
knowledge needed to use it - these steps just get the tool running on your
computer.

## One-time setup

You need Python 3 installed. Then, from the `Scrapping` folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

(Skip this if `.venv` already exists - someone already set it up.)

## Every time you want to score photos

1. Open a terminal in the `Scrapping` folder and run:

   ```bash
   .venv/bin/uvicorn web.app:app --reload
   ```

2. Leave that terminal window open (it's the server) and open this in your
   browser:

   http://127.0.0.1:8000/annotate

3. Type your name and click **Start / continue**.

4. You'll see one photo at a time with a scoring form:
   - 4 dropdowns (eyelid folds, nasojugal folds, jowls, neck profile), each
     0 (none) to 4 (severe), or **NA** if that sign just isn't judgeable in
     this particular photo (angle, blur, etc.) - don't guess, use NA.
   - photo quality / angle
   - a comments box for anything worth flagging
5. Click **Submit & next photo**. Repeat until you see "All done — thank
   you!" (100 photos in this test batch).

Your progress is saved automatically as you go (both on the server and
remembered in your browser), so it's fine to close the tab and come back
later with the same name - it'll pick up where you left off and won't show
you a photo twice.

Made a mistake on an earlier photo? Click **my scored photos** at the top of
the page - it lists everything you've already scored with your saved answers.
Hit **Edit** on any of them to fix it; saving takes you back to that list
without disturbing your place in the main queue.

When you're done, stop the server with `Ctrl+C` in the terminal (or just
leave it running for others).

## Why "same batch, by name"?

Everyone who does this test scores the exact same 50 pairs (100 photos) -
that overlap is the whole point, it's what lets us later compare scores
between people and see if we actually agree. Your name is just how the tool
tracks which of those 100 you've already done.

## More detail / troubleshooting

See the "FLR reliability test (`/annotate`)" section in
[README.md](README.md) for how the batch was sampled, where the data/scores
are stored, and how the scoring rubric can be tweaked later.

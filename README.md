# blogger
This is a script to compile a buch of markdown and html into a website. I use it to compile my own site.


# the gist

So I used to compile my blog/personal website with jekyll because that's what pages supports. However I continually got annoyed with wanting to do something in markdown that
either just wasn't supported or wasn't well supported or wasn't easy or intuitive to do. Often my struggles stemed from the fact that I didn't know ruby (and don't really want to take
the time to learn it if I can avoid it). So one day I got annoyed enough with some such thing I wanted to do and though "I can do this in 5 minutes with python." 
2 days later I had a semi workable replacement for jekyll to compile my site that did what I wanted.

So basically blogger is that replacement. It's just a little side tool I wrote quickly and just kept fiddling with it here and there. Each time I come back to add something to my site
or write a new blog post I find something that's missing from the tool or something that would be nice to have that's relativily easy to add.
At this point it's as good if not better than Jekyll (for my use anyway).
It's pretty easy to understand from the code if only a little messy, and it supports user extension pretty well so you can basically make it do whatever you want.
The way that it implements extension is pretty sketchy in that it just naively runs code imported from the user so you gotta be careful not to just go compiling any old site
(not that there are any sites that written for blogger other than my own. lol).

Anyway I'm not gonna write a real doc just thought I'd explain this in case anyone ever stumbles across this and is curious. PRs are welcome but likely to be ignored for a long time.
✌

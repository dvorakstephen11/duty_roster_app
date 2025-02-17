Here are some of my thoughts on a duty roster web app:

```
1. Duty Roster web app
I was raised in the church of Christ, which is a denomination that is conservative in its worship practices. They don't have a band or a choir, and instead members of the congregation lead the worship service with such activities as singing, praying, preaching (which is usually done by a paid preacher), and officiating the Lord's Supper. 

These churches often create "duty rosters" for the congregation that tell everyone when they're scheduled to lead or participate in a certain act of worship. Lots of churches still do this manually. I know there are competing products, but I also happen to have access to the email addresses of probably 300-500 churches, so I can market my product that way. 

I suspect this is a very simple app and a cheap one to maintain. The church admin for the program would set up their information (worship times, worship activities, leaders, rules for scheduling, etc.), much of which could be based off of common templates and updated with some natural language input to an LLM API, which might be speech-to-text-to-function-call or speech-to-text-to-function-call-to-speech. Anyway, a very easy method of onboarding. Then they would generate their duty roster for the month (or for however many months they want, up to 12 months in advance), and the app would send out emails or texts (depending on the subscription level) to the people on the roster informing them of their upcoming assignments for the month. The users could go to the web app and see their upcoming assignments, but also request substitutions, and these substitutions would be performed automatically (or optionally conditionally upon approval from an admin).

The most complicated part of this would be the scheduling rules, but I suspect this is something that isn't extremely hard to implement. I imagine this could reasonably bring in $400-$600 per month if I charge $10/month. Maybe $20/month for a version with text notifications.

I would think I could do this in a Python Flash app, perhaps in just a couple of weeks. 
```

Implement it. Spare no expense, please implement dummy versions of all the major features you could care about without cutting corners and without using any fancy packages. Please spend time making the UI actually look pretty!
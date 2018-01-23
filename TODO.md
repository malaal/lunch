# TODO

## DO NOW
  - Improve the Results page:
    - Include the ties (if the event is active) or the winner and ties (if completed)
    - Include the schultze outputs on the results page
    - Make a clean sidebar to click for detailed results
    - In the sidebar show "date: Winner" or "date: Voting"
  - Put a reminder link to the results page on the "vote received" page, and on the end-event email
  
  - Set a minimum rank threshold below which restaurants are retired from the list
    - This won't work since ranks are 0-5
    - Perhaps: Enforce a time window or number of votes beyond which a restaurant is removed with a below-threshold rank

## DO LATER  
  - Only use a tie-breaker if the vote doesn't have a natural winner
  - If a user goes back to change their vote, populate the screen with their old vote
  - Add a button on the email to have an "I'm not coming" option
    - Include the list of people coming and not coming in the end-of-event email
  - Beautify the CSS for the emails, etc
  - Verify:
    - The ranking algorithm
    - A good selection of restaurant choices in the getChoices algorithm
  - Move global "DEBUG" into the JSON    

## FUTURE IDEAS
  - Improve the SQLAlchemy to be more relationship and less query based?
    - ex: use event = relationship("Event") and event_id=ForeignKey("Event")
    
  - Allow operator to change the number of restaurants that appear in a vote
  - Allow users to "log in" and view their:
    - voting history
    - personal restaurant ranking (vs the global ranking)
  - Allow users to "auto-vote" based on their existing personal ranking
  - Track rank history and plot how restaurants change over time
    - Store entore rank history in the DB or recalculate to show this data? 
    - Should be easily recalculable by only calculating votes up to a certain date
  
  - Page to allow an admin to start a manual event at will, with a fixed list of restaurants
    - Allow this to override the automatic event
    - Or allow admin to manually set up the next automatic event early
  - Add a button to manually end (or cancel) an event
  
  - When a user is removed from the list, what happens to their votes?
    - Stay in place so rankings are continuous
    - Deleted with rankings immediately recalculated
  
  - Restaurant Management:
    - Restaurants need to be effectively removed (such as if they close) without ruining all the DB relationships.
    - Allow admin to modify the name and visit date of a restaurant
  - Improve the ranking algorithm:
    - Ensure the algorithm actually holds up after a few weeks!
    - Add a cooldown so restaurants fade in ranking (and are then more likely to be selected for a new vote)
  - Use a nonce instead of an email address to authenticate users to prevent voter fraud
    - Send the nonce in the email to each user

## BUGS
  - Doesn't work if there are fewer than five restaurants on the list
    - Instruct user to add some before letting Manager start a vote session

-----------------------------------------------------------------------
# NOTES


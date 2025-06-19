# gr-reports
My sister had a cool idea to post her monthly reads to Instagram Stories. She built Stories by saving book covers to a folder on her phone, then taking a screenshot of that folder. I loved the idea and her monthly posts but I wanted to do something more automatic for myself. 

This is a fairly-simple Python script and flask application that grabs a user's Goodreads RSS feed (at most once per 24 hours to avoid hammering Goodreads), downloads book cover images (once, to avoid repeated downloads), and generates fairly simple images sized to be posted to Instagram Stories. Currently, the user's star rating and a snippet of text from the review are included with the image as well. 

The application runs in a Docker container so the web page is available wherever a user sets up that container. 

Docker Compose: 
```yaml
# Example Docker-Compose
services:
  goodreads-collage:
    container_name: goodreads-collage
    image: ghcr.io/b-neufeld/gr-reports:latest
    ports:
      # Port outside container : port inside container 
      - 8010:5000 
    environment:
      # Example URL: https://www.goodreads.com/review/list_rss/5672051?shelf=read (see bottom of "Read" shelf page)
      - GOODREADS_RSS_URL=https://www.goodreads.com/review/list_rss/5672051?shelf=read
      # For header of image
      - USER_NAME=Brahm
    volumes:
      # create and map three volumes for caching RSS feeds, book covers, and collages. 
      - /path/to/local/storage/rss_cache:/app/rss_cache
      - /path/to/local/storage/covers:/app/covers
      - /path/to/local/storage/collages:/app/collages
    restart: unless-stopped
```

Web app:
![image](https://github.com/user-attachments/assets/f3ec45be-dc2f-4e10-a259-7b984b7ecf06)

Example image:
![image](https://github.com/user-attachments/assets/1ce4220a-0847-4ed4-977a-5e1cc9e625b9)


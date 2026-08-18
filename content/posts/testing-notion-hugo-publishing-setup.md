---
title: "This is a Test Post"
date: 2026-08-18
description: "Testing My Notion → Hugo Publishing Setup"
tags: ["Notion", "Testing"]
draft: true
---

## This is a Test Post

This is a test post that I am using to test my My Notion → Hugo Publishing Setup

I'm currently trying to get my blog setup to work a little differently. Instead of writing a post directly in Hugo, I want to be able to write it in **Notion**, mark it as published, and let the rest happen automatically.

### What I'm Testing

There are a few things I want to make sure are working together:

- **Notion:** where I'm writing and managing my posts

- **Notion API:** allowing my sync script to read the database and published posts

- **Python sync script:** converting the Notion content into Hugo Markdown

- **GitHub Actions:** running the sync automatically

- **Git:** committing and pushing the generated files

- **Hugo:** taking those Markdown files and turning them into the actual blog

- **Images:** checking that images inside Notion are downloaded and placed in the right location

- **Frontmatter:** making sure things like title, date, description, tags, and slug make their way from Notion into Hugo correctly

### What I'm Hoping Happens

Ideally, I should be able to write something in Notion, mark it as **Ready**, and then just wait.

The workflow should take care of the rest.

I'm honestly pretty excited to see this work because I've spent quite some time to understand how this pipeline works.

### If This Actually Works...

If this works properly, I'll probably write a separate blog post about the whole setup.

I will document how I put everything together: i.e. **Notion → API → Python → GitHub Actions → Hugo**

That will probably be more interesting than this test post anyway.

For now, though...

**This is me testing whether the system works as expected. **

![Image](/images/posts/testing-notion-hugo-publishing-setup/img1.png)

#!/usr/bin/env python3

import os
import re
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

NOTION_TOKEN = os.environ.get('NOTION_TOKEN')
DATABASE_ID = os.environ.get('NOTION_DATABASE_ID')

OUTPUT_DIR = 'content/posts'
IMAGE_DIR = 'static/images/posts'   

NOTION_API = 'https://api.notion.com/v1'
NOTION_VERSION = '2025-09-03'   

HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Notion-Version': NOTION_VERSION,
    'Content-Type': 'application/json'
}


def get_data_source_id(database_id):
    
    url = f'{NOTION_API}/databases/{database_id}'
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    data = response.json()
    data_sources = data.get('data_sources', [])
    if not data_sources:
        raise RuntimeError('No data sources found on this database.')
    return data_sources[0]['id']


def query_data_source(data_source_id):
   
    url = f'{NOTION_API}/data_sources/{data_source_id}/query'
    payload = {
        'filter': {
            'or': [
                {'property': 'Status', 'select': {'equals': 'Published'}},
                {'property': 'Status', 'select': {'equals': 'Ready'}}
            ]
        },
        'sorts': [
            {'property': 'Published Date', 'direction': 'descending'}
        ]
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json()['results']


def get_page_blocks(page_id):
    blocks = []
    url = f'{NOTION_API}/blocks/{page_id}/children'
    params = {'page_size': 100}
    while url:
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        data = response.json()
        blocks.extend(data['results'])
        if data.get('has_more'):
            params['start_cursor'] = data['next_cursor']
        else:
            url = None
    return blocks


def rich_text_to_markdown(rich_text):
    if not rich_text:
        return ''
    parts = []
    for t in rich_text:
        text = t['plain_text']
        ann = t['annotations']
        if ann['code']:
            text = f'`{text}`'
        if ann['bold']:
            text = f'**{text}**'
        if ann['italic']:
            text = f'*{text}*'
        if ann['strikethrough']:
            text = f'~~{text}~~'
        if t.get('href'):
            text = f'[{text}]({t["href"]})'
        parts.append(text)
    return ''.join(parts)


def download_image(url, slug, index):
   
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    parsed_path = urlparse(url).path
    ext = Path(parsed_path).suffix.split('?')[0]
    if not ext or len(ext) > 5:
        ext = '.png'

    folder = Path(IMAGE_DIR) / slug
    folder.mkdir(parents=True, exist_ok=True)
    filename = f'img{index}{ext}'
    filepath = folder / filename
    filepath.write_bytes(resp.content)

    return f'/images/posts/{slug}/{filename}'


def notion_to_markdown(blocks, slug):
    lines = []
    image_index = 0

    for block in blocks:
        btype = block['type']

        if btype == 'paragraph':
            text = rich_text_to_markdown(block['paragraph']['rich_text'])
            if text.strip():
                lines.append(f'{text}\n')

        elif btype == 'heading_1':
            lines.append(f'## {rich_text_to_markdown(block["heading_1"]["rich_text"])}\n')
        elif btype == 'heading_2':
            lines.append(f'### {rich_text_to_markdown(block["heading_2"]["rich_text"])}\n')
        elif btype == 'heading_3':
            lines.append(f'#### {rich_text_to_markdown(block["heading_3"]["rich_text"])}\n')

        elif btype == 'bulleted_list_item':
            lines.append(f'- {rich_text_to_markdown(block["bulleted_list_item"]["rich_text"])}\n')
        elif btype == 'numbered_list_item':
            lines.append(f'1. {rich_text_to_markdown(block["numbered_list_item"]["rich_text"])}\n')

        elif btype == 'code':
            code = rich_text_to_markdown(block['code']['rich_text'])
            language = block['code']['language']
            lines.append(f'```{language}\n{code}\n```\n')

        elif btype == 'quote':
            lines.append(f'> {rich_text_to_markdown(block["quote"]["rich_text"])}\n')

        elif btype == 'divider':
            lines.append('---\n')

        elif btype == 'image':
            src = block['image'].get('file', {}).get('url') or block['image'].get('external', {}).get('url')
            if src:
                image_index += 1
                try:
                    local_path = download_image(src, slug, image_index)
                    caption = rich_text_to_markdown(block['image'].get('caption', []))
                    alt = caption if caption else 'Image'
                    lines.append(f'![{alt}]({local_path})\n')
                except Exception as e:
                    print(f'  ! Failed to download image {image_index}: {e}')

    return '\n'.join(lines)


def extract_properties(page):
    props = page['properties']

    title_prop = props.get('Name') or props.get('Title')
    title = title_prop['title'][0]['plain_text'] if title_prop and title_prop.get('title') else 'Untitled'

    date_prop = props.get('Published Date') or props.get('Date')
    date = date_prop['date']['start'] if date_prop and date_prop.get('date') else datetime.now().isoformat()

    slug_prop = props.get('Slug')
    slug = slug_prop['rich_text'][0]['plain_text'] if slug_prop and slug_prop.get('rich_text') else ''
    if not slug:
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

    desc_prop = props.get('Description')
    description = desc_prop['rich_text'][0]['plain_text'] if desc_prop and desc_prop.get('rich_text') else ''

    tags_prop = props.get('Tags')
    tags = [t['name'] for t in tags_prop['multi_select']] if tags_prop and tags_prop.get('multi_select') else []

    status_prop = props.get('Status')
    status = status_prop['select']['name'] if status_prop and status_prop.get('select') else 'Draft'
    is_draft = status != 'Published'   # Ready -> draft:true, Published -> draft:false

    return {'title': title, 'date': date, 'slug': slug, 'description': description, 'tags': tags, 'is_draft': is_draft}


def write_hugo_post(properties, content):
    slug = properties['slug']
    filepath = Path(OUTPUT_DIR) / f'{slug}.md'
    tags_str = ', '.join(f'"{t}"' for t in properties['tags'])

    front_matter = f"""---
title: "{properties['title']}"
date: {properties['date']}
description: "{properties['description']}"
tags: [{tags_str}]
draft: {str(properties['is_draft']).lower()}
---

"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(front_matter + content, encoding='utf-8')
    print(f'  ✓ {filepath}')


def sync():
    print('Resolving data source...')
    data_source_id = get_data_source_id(DATABASE_ID)

    print('Querying published posts...')
    pages = query_data_source(data_source_id)
    print(f'Found {len(pages)} published post(s)\n')

    for page in pages:
        properties = extract_properties(page)
        print(f'Syncing: {properties["title"]}')
        blocks = get_page_blocks(page['id'])
        content = notion_to_markdown(blocks, properties['slug'])
        write_hugo_post(properties, content)

    print('\nDone.')


if __name__ == '__main__':
    if not NOTION_TOKEN:
        raise SystemExit('NOTION_TOKEN not set')
    if not DATABASE_ID:
        raise SystemExit('NOTION_DATABASE_ID not set')
    sync()
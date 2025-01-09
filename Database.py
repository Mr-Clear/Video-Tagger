import sqlite3
from datetime import datetime
from typing import List, Iterable, Dict

from VideoFile import VideoFile


class Database:
    def __init__(self, db_path):
        self.db_path = db_path

        self.settings = {}
        self.settings_loaded = False

        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()

        self.create_tables()

    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            size INTEGER NOT NULL,
            date_modified TIMESTAMP NOT NULL,
            duration FLOAT,
            rating INTEGER DEFAULT NULL
            )''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_has_tag (
                file_id INTEGER NOT NULL REFERENCES files(id),
                tag_id INTEGER NOT NULL REFERENCES tags(id))''')
        self.cursor.execute('''CREATE INDEX IF NOT EXISTS idx_file_id ON file_has_tag(file_id)''')
        self.cursor.execute('''CREATE INDEX IF NOT EXISTS idx_tag_id ON file_has_tag(tag_id)''')
        self.conn.commit()

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT)''')

    def close(self):
        self.conn.close()

    def get_file(self, file_id: int) -> VideoFile:
        self.cursor.execute('SELECT path, size, date_modified, duration, rating FROM files WHERE id = ?', (file_id,))
        path, size, date_modified, duration, rating = self.cursor.fetchone()
        self.cursor.execute('SELECT name FROM tags INNER JOIN file_has_tag ON tags.id = file_has_tag.tag_id WHERE '
                            'file_has_tag.file_id = ?', (file_id,))
        tags = {tag_row[0] for tag_row in self.cursor.fetchall()}
        return VideoFile(file_id, path, size, datetime.fromisoformat(date_modified), duration, rating, tags)

    def find_file(self, path: str) -> VideoFile | None:
        self.cursor.execute('SELECT id FROM files WHERE path = ?', (path,))
        file_id = self.cursor.fetchone()
        return self.get_file(file_id[0]) if file_id is not None else None

    def get_files(self) -> List[VideoFile]:
        self.cursor.execute('SELECT id FROM files ORDER BY path')
        file_ids = [row[0] for row in self.cursor.fetchall()]
        return [self.get_file(file_id) for file_id in file_ids]

    def get_files_with_tags(self, whitelist: Iterable[str], blacklist: Iterable[str]) -> List[VideoFile]:
        self.cursor.execute('SELECT id FROM files '
                            ' WHERE id IN (SELECT file_id FROM file_has_tag '
                            '               WHERE tag_id IN (SELECT id FROM tags WHERE name IN (?))) '
                            '                 AND id NOT IN (SELECT file_id FROM file_has_tag '
                            '                                 WHERE tag_id IN (SELECT id FROM tags WHERE name IN (?)))',
                            (whitelist, blacklist))
        file_ids = [row[0] for row in self.cursor.fetchall()]
        return [self.get_file(file_id) for file_id in file_ids]

    def add_file(self, file: VideoFile) -> int:
        self.cursor.execute('SELECT id FROM files WHERE path = ?', (file.path,))
        if self.cursor.fetchone() is not None:
            return -1  # File already exists
        self.cursor.execute('INSERT INTO files (path, size, date_modified, duration, rating) VALUES (?, ?, ?, ?, ?)',
                            (file.path, file.size, file.date_modified.isoformat(), file.duration, file.rating))
        file_id = self.cursor.lastrowid
        for tag in file.tags:
            self.set_tag(file_id, tag)
        self.conn.commit()
        return file_id

    def get_tags(self) -> Dict[str, int]:
        self.cursor.execute('SELECT name, COUNT(file_has_tag.tag_id) '
                            '  FROM tags LEFT JOIN file_has_tag ON tags.id = file_has_tag.tag_id GROUP BY tags.id')
        return {row[0]: row[1] for row in self.cursor.fetchall()}

    def add_tag(self, tad_name: str):
        self.cursor.execute('INSERT INTO tags (name) VALUES (?)', (tad_name,))
        self.conn.commit()

    def get_tag_id(self, tag: str) -> int | None:
        self.cursor.execute('SELECT id FROM tags WHERE name = ?', (tag,))
        tag_id = self.cursor.fetchone()
        return tag_id[0] if tag_id is not None else None

    def set_tag(self, file_id: int, tag: str):
        tag_id = self.get_tag_id(tag)
        if tag_id is None:
            self.cursor.execute('INSERT INTO tags (name) VALUES (?)', (tag,))
            tag_id = self.cursor.lastrowid
        self.cursor.execute('SELECT 1 FROM file_has_tag WHERE file_id = ? AND tag_id = ?', (file_id, tag_id))
        if self.cursor.fetchone() is None:
            self.cursor.execute('INSERT INTO file_has_tag (file_id, tag_id) VALUES (?, ?)', (file_id, tag_id))
            self.conn.commit()

    def remove_tag(self, file_id: int, tag: str):
        tag_id = self.get_tag_id(tag)
        if tag_id is None:
            return
        self.cursor.execute('DELETE FROM file_has_tag WHERE file_id = ? AND tag_id = ?', (file_id, tag_id))
        self.conn.commit()

    def delete_tag(self, tag: str):
        tag_id = self.get_tag_id(tag)
        if tag_id is None:
            return
        self.cursor.execute('DELETE FROM file_has_tag WHERE tag_id = ?', (tag_id,))
        self.cursor.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
        self.conn.commit()

    def set_rating(self, file_id: int, rating: int | None):
        self.cursor.execute('UPDATE files SET rating = ? WHERE id = ?', (rating, file_id))
        self.conn.commit()

    def remove_file(self, file_id: int):
        self.cursor.execute('DELETE FROM file_has_tag WHERE file_id = ?', (file_id,))
        self.cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
        self.conn.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        self._load_settings()
        return self.settings.get(key, default)

    def set_setting(self, key: str, value: str):
        self.settings[key] = value
        self.cursor.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        self.conn.commit()

    def remove_setting(self, key: str):
        self.settings.pop(key, None)
        self.cursor.execute('DELETE FROM settings WHERE key = ?', (key,))
        self.conn.commit()

    def get_settings(self) -> Dict[str, str]:
        self._load_settings()
        print("len(self.settings)", len(self.settings))
        return self.settings

    def _load_settings(self):
        if not self.settings_loaded:
            self.cursor.execute('SELECT key, value FROM settings')
            self.settings = {row[0]: row[1] for row in self.cursor.fetchall()}
            self.settings_loaded = True

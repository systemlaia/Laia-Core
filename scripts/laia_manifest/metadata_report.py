#!/usr/bin/env python3
from pathlib import Path
import argparse, sqlite3, datetime

def q(conn, sql):
    return conn.execute(sql).fetchall()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="archive/catalog/photo_metadata.sqlite")
    p.add_argument("--out", default="archive/reports")
    args = p.parse_args()

    db = Path(args.db).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    md = out / f"metadata_report_{stamp}.md"

    total = q(conn, "select count(*) from photo_metadata")[0][0]
    models = q(conn, """
        select coalesce(nullif(json_extract(exif_json,'$.Model'),''),'UNKNOWN') as model, count(*)
        from photo_metadata
        group by model
        order by count(*) desc
    """)
    filetypes = q(conn, """
        select extension, count(*)
        from photo_metadata
        group by extension
        order by count(*) desc
    """)
    dates = q(conn, """
        select min(json_extract(exif_json,'$.DateTimeOriginal')),
               max(json_extract(exif_json,'$.DateTimeOriginal'))
        from photo_metadata
        where json_extract(exif_json,'$.DateTimeOriginal') is not null
    """)[0]
    folders = q(conn, """
        select substr(relative_path, 1, instr(relative_path || '/', '/') - 1) as folder, count(*)
        from photo_metadata
        group by folder
        order by count(*) desc
        limit 20
    """)
    samples = q(conn, """
        select relative_path,
               coalesce(json_extract(exif_json,'$.Model'),''),
               coalesce(json_extract(exif_json,'$.DateTimeOriginal'),'')
        from photo_metadata
        limit 20
    """)

    with md.open("w") as f:
        f.write("# LAIA Photo Metadata Report\n\n")
        f.write(f"- Generated: `{stamp}`\n")
        f.write(f"- Database: `{db}`\n")
        f.write(f"- Rows in catalog: `{total}`\n\n")

        f.write("## Date Range\n\n")
        f.write(f"- Earliest DateTimeOriginal: `{dates[0]}`\n")
        f.write(f"- Latest DateTimeOriginal: `{dates[1]}`\n\n")

        f.write("## Camera Models\n\n")
        f.write("| Model | Count |\n|---|---:|\n")
        for model, count in models:
            f.write(f"| `{model}` | {count} |\n")

        f.write("\n## File Types\n\n")
        f.write("| Extension | Count |\n|---|---:|\n")
        for ext, count in filetypes:
            f.write(f"| `{ext}` | {count} |\n")

        f.write("\n## Top Folders\n\n")
        f.write("| Folder | Count |\n|---|---:|\n")
        for folder, count in folders:
            f.write(f"| `{folder}` | {count} |\n")

        f.write("\n## Sample Rows\n\n")
        f.write("| Relative Path | Model | DateTimeOriginal |\n|---|---|---|\n")
        for path, model, dto in samples:
            f.write(f"| `{path}` | `{model}` | `{dto}` |\n")

        f.write("\n## Archivist Notes\n\n")
        f.write("- This report is derived from SQLite metadata extracted by exiftool.\n")
        f.write("- No source archive files were modified.\n")
        f.write("- Aggregate claims are database-backed.\n")

    print(f"MD: {md}")

if __name__ == "__main__":
    main()

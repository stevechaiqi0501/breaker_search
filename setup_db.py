import sqlite3
import pandas as pd

DATABASE_FILE = "cutting_selection.db"

def main():
    # ブレーカー用Excelを読み込み
    df_breaker = pd.read_excel("dummy_data_breakerz.xlsx", sheet_name="Sheet1", engine="openpyxl")
    # 素材用Excelを読み込み
    df_material = pd.read_excel("dummy_data_materialz.xlsx", sheet_name="Sheet1", engine="openpyxl")

    conn = sqlite3.connect(DATABASE_FILE)
    c = conn.cursor()

    # 既存テーブルがあれば削除
    c.execute("DROP TABLE IF EXISTS breakers")
    c.execute("DROP TABLE IF EXISTS materials")

    # breakers テーブル作成 (加工種別を含む / 特徴は削除)
    c.execute("""
    CREATE TABLE breakers (
        id INTEGER PRIMARY KEY,
        name TEXT,
        加工種別 TEXT,
        切込み最小 REAL,
        切込み推奨 REAL,
        切込み最大 REAL,
        送り量最小 REAL,
        送り量推奨 REAL,
        送り量最大 REAL
    )
    """)

    # materials テーブル作成 (加工種別あり / 最終優先度あり / 特徴削除)
    c.execute("""
    CREATE TABLE materials (
        id INTEGER PRIMARY KEY,
        name TEXT,
        加工種別 TEXT,
        最終優先度 TEXT,
        切削速度最小 REAL,
        切削速度推奨 REAL,
        切削速度最大 REAL
    )
    """)

    # breakers にINSERT
    for _, row in df_breaker.iterrows():
        c.execute("""
            INSERT INTO breakers
            (id, name, 加工種別,
             切込み最小, 切込み推奨, 切込み最大,
             送り量最小, 送り量推奨, 送り量最大)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            row["id"],
            row["name"],
            row["加工種別"],
            row["切込み最小"],
            row["切込み推奨"],
            row["切込み最大"],
            row["送り量最小"],
            row["送り量推奨"],
            row["送り量最大"]
        ))

    # materials にINSERT
    for _, row in df_material.iterrows():
        c.execute("""
            INSERT INTO materials
            (id, name, 加工種別, 最終優先度,
             切削速度最小, 切削速度推奨, 切削速度最大)
            VALUES (?,?,?,?,?,?,?)
        """, (
            row["id"],
            row["name"],
            row["加工種別"],
            row["最終優先度"],
            row["切削速度最小"],
            row["切削速度推奨"],
            row["切削速度最大"]
        ))

    conn.commit()
    conn.close()

    print(f"DB '{DATABASE_FILE}' に新仕様のテーブルを作成し、ExcelからデータをINSERTしました。")

if __name__ == "__main__":
    main()

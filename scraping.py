import asyncio
from playwright.async_api import async_playwright
import pymysql

# ================= DB =================
db = pymysql.connect(
    host="localhost",
    user="root",
    password="",
    database="wilayah_indonesia",
    autocommit=True
)

cursor = db.cursor()


# ================= DELAY =================
async def delay(ms):
    await asyncio.sleep(ms / 1000)


# ================= PROVINSI =================
async def get_provinsi(page):
    await page.goto(
        "https://kodepos.co.id/kodepos",
        timeout=120000,
        wait_until="domcontentloaded"
    )
    await page.wait_for_selector(
        "section a h3",
        timeout=120000
    )

    all_data = []
    seen = set()

    while True:
        # =========================
        # AMBIL DATA DI PAGE INI
        # =========================
        prov_list = await page.eval_on_selector_all(
            "section a h3",
            """els => els.map(el => {
                const a = el.closest('a');
                const span = a.querySelector('span');

                return {
                    nama: el.innerText.trim(),
                    slug: a.getAttribute('href').replace('/kodepos/',''),
                    pulau: span ? span.innerText.trim() : ''
                };
            })"""
        )

        print(f"📄 Ambil provinsi: {len(prov_list)}")

        for p in prov_list:
            key = p['slug']
            if key in seen:
                continue

            seen.add(key)
            all_data.append(p)

        # =========================
        # CEK NEXT
        # =========================
        next_btn = await page.query_selector('button[aria-label="Halaman berikutnya"]')

        if not next_btn:
            break

        disabled = await next_btn.get_attribute("disabled")

        if disabled is not None:
            break

        # klik next
        await next_btn.click()
        await page.wait_for_timeout(500)

    print(f"✅ Total provinsi: {len(all_data)}")

    return all_data


# ================= KOTA =================
async def get_kota(page, slug_prov):
    await page.goto(f"https://kodepos.co.id/kodepos/{slug_prov}")
    await page.wait_for_selector("ul li")

    return await page.eval_on_selector_all(
        "ul li",
        """els => els.map(el => {
            const a = el.querySelector('a');
            if (!a) return null;

            const link = a.getAttribute('href');
            if (!link || link.split('/').length !== 4) return null;

            // ambil nama dari div yang benar
            const namaDiv = el.querySelector('div.text-gray-900');
            if (!namaDiv) return null;

            const nama = namaDiv.innerText.trim();

            if (nama === 'Detail') return null;

            return {
                nama,
                slug: link.split('/').pop()
            };
        }).filter(Boolean)"""
    )


# ================= KECAMATAN =================
async def get_kecamatan(page, slug_prov, slug_kota):
    await page.goto(f"https://kodepos.co.id/kodepos/{slug_prov}/{slug_kota}")
    await page.wait_for_selector("a")

    return await page.eval_on_selector_all(
        "a",
        """els => els
            .filter(el => {
                const href = el.getAttribute('href');
                return href && href.split('/').length === 5 && el.innerText.trim() !== 'Detail';
            })
            .map(el => ({
                nama: el.innerText.trim(),
                slug: el.getAttribute('href').split('/').pop()
            }))
        """
    )


# ================= DESA =================
async def get_desa(page, slug_prov, slug_kota, slug_kec, id_prov, id_kota, id_kec):
    url = f"https://kodepos.co.id/kodepos/{slug_prov}/{slug_kota}/{slug_kec}"
    await page.goto(url)
    await page.wait_for_selector("table tbody tr")

    all_data = set()

    while True:
        # =========================
        # AMBIL DATA DI PAGE SEKARANG
        # =========================
        rows = await page.query_selector_all("table tbody tr")

        print(f"         📄 Ambil page ({len(rows)})")

        for row in rows:
            td = await row.query_selector_all("td")

            if len(td) < 7:
                continue

            nama = (await td[1].inner_text()).strip()
            kode = (await td[2].inner_text()).strip()
            kemendagri = (await td[3].inner_text()).strip()
            koordinat = (await td[4].inner_text()).strip()
            elevasi = (await td[5].inner_text()).strip()
            zona = (await td[6].inner_text()).strip()

            key = f"{id_kec}-{kemendagri}"

            if key in all_data:
                continue

            all_data.add(key)

            cursor.execute("""
                SELECT id_desa FROM desa 
                WHERE id_kecamatan=%s
                AND kode_kemendagri=%s
            """, (id_kec, kemendagri))

            if cursor.fetchone():
                continue

            lat, lng = None, None
            if "," in koordinat:
                try:
                    lat, lng = [float(x.strip()) for x in koordinat.split(",")]
                except:
                    pass

            # INSERT DESA
            cursor.execute("""
                INSERT INTO desa 
                (id_kecamatan, nama_desa, kode_kemendagri, koordinat, latitude, longitude, elevasi, zona_waktu)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (id_kec, nama, kemendagri, koordinat, lat, lng, elevasi, zona))

            id_desa = cursor.lastrowid

            # INSERT KODE POS
            if kode:
                cursor.execute("""
                    INSERT INTO kode_pos 
                    (id_provinsi, id_kota, id_kecamatan, id_desa, kode_pos)
                    VALUES (%s, %s, %s, %s, %s)
                """, (id_prov, id_kota, id_kec, id_desa, kode))

        # =========================
        # CEK NEXT
        # =========================
        next_btn = await page.query_selector('button[aria-label="Halaman berikutnya"]')

        if not next_btn:
            break

        disabled = await next_btn.get_attribute("disabled")

        if disabled is not None:
            break

        # klik next
        await next_btn.click()
        await page.wait_for_timeout(400)

    print(f"         ✅ Total unik: {len(all_data)}")


# ================= RESUME =================
def get_last_progress():
    cursor.execute("""
        SELECT 
            p.slug AS prov_slug,
            k.slug AS kota_slug,
            kc.slug AS kec_slug
        FROM desa d
        JOIN kecamatan kc 
            ON d.id_kecamatan = kc.id_kecamatan
        JOIN kota_kab k 
            ON kc.id_kota = k.id_kota
        JOIN provinsi p 
            ON k.id_provinsi = p.id_provinsi
        ORDER BY d.id_desa DESC
        LIMIT 1
    """)

    row = cursor.fetchone()

    if not row:
        return None

    return {
        "prov": row[0],
        "kota": row[1],
        "kec": row[2]
    }

# ================= MAIN =================
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(120000)

        # =========================
        # AMBIL SEMUA PROVINSI
        # =========================
        prov_list = await get_provinsi(page)

        # =========================
        # RESUME
        # =========================
        resume = get_last_progress()

        print("\n🔄 RESUME:", resume)

        start_prov = resume is None

        # =========================
        # LOOP PROVINSI
        # =========================
        for prov in prov_list:

            # =========================
            # SKIP SEBELUM PROV TERAKHIR
            # =========================
            if not start_prov:
                if prov['slug'] == resume['prov']:
                    start_prov = True
                else:
                    continue

            print(f"\n📍 {prov['nama']}")

            # =========================
            # CEK / INSERT PROVINSI
            # =========================
            cursor.execute("""
                SELECT id_provinsi 
                FROM provinsi 
                WHERE slug=%s
            """, (prov['slug'],))

            row = cursor.fetchone()

            if row:
                id_prov = row[0]
            else:
                cursor.execute("""
                    INSERT INTO provinsi
                    (nama_provinsi, slug, pulau)
                    VALUES (%s, %s, %s)
                """, (
                    prov['nama'],
                    prov['slug'],
                    prov['pulau']
                ))

                id_prov = cursor.lastrowid

            # =========================
            # AMBIL KOTA
            # =========================
            kota_list = await get_kota(page, prov['slug'])

            # =========================
            # LOOP KOTA
            # =========================
            for kota in kota_list:

                # =========================
                # RESUME KOTA
                # =========================
                if resume and prov['slug'] == resume['prov']:
                    if kota['slug'] < resume['kota']:
                        continue

                print(f"   🏙️ {kota['nama']}")

                tipe = "Kota" if "kota" in kota['nama'].lower() else "Kabupaten"

                # =========================
                # CEK / INSERT KOTA
                # =========================
                cursor.execute("""
                    SELECT id_kota
                    FROM kota_kab
                    WHERE slug=%s
                    AND id_provinsi=%s
                """, (
                    kota['slug'],
                    id_prov
                ))

                row = cursor.fetchone()

                if row:
                    id_kota = row[0]
                else:
                    cursor.execute("""
                        INSERT INTO kota_kab
                        (id_provinsi, nama_kota, slug, tipe)
                        VALUES (%s, %s, %s, %s)
                    """, (
                        id_prov,
                        kota['nama'],
                        kota['slug'],
                        tipe
                    ))

                    id_kota = cursor.lastrowid

                # =========================
                # AMBIL KECAMATAN
                # =========================
                kec_list = await get_kecamatan(
                    page,
                    prov['slug'],
                    kota['slug']
                )

                # =========================
                # LOOP KECAMATAN
                # =========================
                for kec in kec_list:

                    # =========================
                    # RESUME KECAMATAN
                    # =========================
                    if (
                        resume and
                        prov['slug'] == resume['prov'] and
                        kota['slug'] == resume['kota']
                    ):
                        if kec['slug'] <= resume['kec']:
                            continue

                    print(f"      🏘️ {kec['nama']}")

                    # =========================
                    # CEK / INSERT KECAMATAN
                    # =========================
                    cursor.execute("""
                        SELECT id_kecamatan
                        FROM kecamatan
                        WHERE slug=%s
                        AND id_kota=%s
                    """, (
                        kec['slug'],
                        id_kota
                    ))

                    row = cursor.fetchone()

                    if row:
                        id_kec = row[0]
                    else:
                        cursor.execute("""
                            INSERT INTO kecamatan
                            (id_kota, nama_kecamatan, slug)
                            VALUES (%s, %s, %s)
                        """, (
                            id_kota,
                            kec['nama'],
                            kec['slug']
                        ))

                        id_kec = cursor.lastrowid

                    # =========================
                    # SCRAPING DESA
                    # =========================
                    await get_desa(
                        page,
                        prov['slug'],
                        kota['slug'],
                        kec['slug'],
                        id_prov,
                        id_kota,
                        id_kec
                    )

                    await delay(150)

        await browser.close()

    print("\n🔥 SELESAI 🔥")


asyncio.run(main())
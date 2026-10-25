-- H1 on the old SQLite snapshot: sqlite3 -header -column data/seam.db < api/model/queries/h1_sqlite.sql
create temp view f as
with t as (select source, json_extract(tags,'$.slot') slot, json_extract(tags,'$.category') cat,
  lower(coalesce(json_extract(tags,'$.material'),'')) mat,
  lower(json_extract(listing,'$.title')||' '||coalesce(json_extract(listing,'$.description'),'')) txt, id from items)
select *, (mat like '%leather%' or cat='leather_jacket') tag_l, (txt like '%leather%') txt_l,
  (txt like '%faux%' or txt like '%vegan%' or txt like '%pleather%') txt_faux from t;
select source, slot, count(*) n, round(100.0*avg(tag_l),1) tag_pct, round(100.0*avg(txt_l),1) text_pct, sum(tag_l and not txt_l) tag_only, sum(txt_l and not tag_l) text_only from f group by 1,2
union all select source,'ALL',count(*),round(100.0*avg(tag_l),1),round(100.0*avg(txt_l),1),sum(tag_l and not txt_l),sum(txt_l and not tag_l) from f group by 1
union all select 'ALL','ALL',count(*),round(100.0*avg(tag_l),1),round(100.0*avg(txt_l),1),sum(tag_l and not txt_l),sum(txt_l and not tag_l) from f;

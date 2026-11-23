import csv,os
A="https://assets.publishing.service.gov.uk/media/"
E="https://environment.data.gov.uk/api/file/download?fileDataSetId="
OGL="OGL v3.0"
F="Finance & Budget";H="Workforce & Diversity";N="Environment & Nature";D="Digital & Data";R="Flood, Water & Coastal Risk"
rows=[
("fin-01-ea-annual-report-2024-25.pdf","Environment Agency annual report and accounts 2024 to 2025",F,"",A+"6908c7955e080b1224898196/E03466580_Environment_Agency_ARA_2024-25_Accessible.pdf",OGL,"real","y"),
("fin-02-defra-core-tables-2024-25.xlsx","Defra Core Tables (resource and capital budget) 2024-25",F,"",  "https://s3.eu-west-1.amazonaws.com/data.defra.gov.uk/ops/core_tables/Defra+Core+Tables+2024-25_13112025.xlsx",OGL,"real","y"),
("fin-03-fisheries-licence-income-2024-25.pptx","Fisheries annual report 2024 to 2025: how we spend fishing licence income (slides)",F,N,"https://www.gov.uk/government/publications/fisheries-annual-report-2024-to-2025-how-we-spend-fishing-licence-income/fisheries-annual-report-2024-to-2025-how-we-spend-fishing-licence-income",OGL,"derived (python-pptx, verbatim page text)","y"),
("hr-01-workforce-diversity-stats-q3-2013-14.xlsx","Environment Agency Workforce Diversity Statistics Q3 2013-14",H,"",A+"5a7ce58ce5274a724f0be2d4/LIT_9101_Environment_Agency_Workforce_Diversity_Statistics_Q3_2013_14_426ba7.xlsx",OGL,"real","y"),
("hr-02-diversity-dashboard-q3-2013-14.xlsx","Environment Agency diversity dashboard Q3 2013-14",H,"",A+"5a7c9c90e5274a30fa38fdea/LIT_9123_Environment_Agency_Diversity_Dashboard_Q3_2013_14_ac5281.xlsx",OGL,"real","y"),
("hr-03-defra-workforce-monitoring-2016.pdf","Defra 2016 Workforce Monitoring Report (Defra and Executive Agencies)",H,"",A+"5f8432c78fa8f50456bb8b9d/defra-workforce-monitoring-2016.pdf",OGL,"real","y"),
("hr-04-ea-pay-gap-2025.pptx","Environment Agency: pay gap 2025 (slides)",H,"","https://www.gov.uk/government/publications/environment-agency-pay-gap/environment-agency-pay-gap-2025",OGL,"derived (python-pptx, verbatim page text)","y"),
("env-01-office-waste-ea-premises-2014-15.xlsx","Office waste produced at Environment Agency premises 2014-15",N,"",E+"95fe8c72-c5c6-4b0f-8515-4eb3bf7f8bce&fileName=Office_waste_produced_at_Environment_Agency_premises_2014-15.xlsx",OGL+" (EA open data)","real","y"),
("env-02-waste-investigations-report.xlsx","Waste Investigations Report",N,"",E+"a15b347f-c277-4139-8988-a3ae2fd8b385&fileName=Waste_Investigations_Report.xlsx",OGL+" (EA open data)","real","y"),
("env-03-preconsented-waste-recovery-sites.xlsx","Preconsented waste recovery sites",N,"",E+"1adcbe10-2517-44cb-a8b5-d9f7f621b05d&fileName=Preconsented_waste_recovery_sites.xlsx",OGL+" (EA open data)","real","y"),
("env-04-seagrass-potential-documentation.docx","Seagrass Potential dataset documentation v3",N,D,E+"4599f8f2-d023-46ac-9934-8fc853eabca0&fileName=Seagrass_Potential_Dataset_Documentation v3.docx",OGL+" (EA open data)","real","y"),
("env-05-working-with-nature-report.pdf","Working with nature (Chief Scientist's Group report, July 2022)",N,R,"https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/1088383/Working_with_nature_-_report.pdf",OGL,"real","y"),
("env-06-ea-ambition-2020-scanned.pdf","Creating a better place: our ambition to 2020 (June 2018), page images only",N,R,A+"5b112b08ed915d2cb4e190c6/Environment_Agency_our_ambition_to_2020.pdf",OGL,"derived (original pages rasterised to images, text layer removed)","n"),
("dig-01-defra-digital-data-strategy-2023-30.pdf","Defra group digital and data transformation strategy 2023 to 2030",D,"",A+"655733af046ed400148b9a9d/Defra_group_digital_and_data_transformation_strategy.pdf",OGL,"real","y"),
("dig-02-lidar-technical-guide.docx","LIDAR Composite Technical Information Guide (2022)",D,R,E+"2ead20b8-c67d-4328-8980-0f8151a6094b&fileName=LIDAR Composite Technical Information Guide.docx",OGL+" (EA open data)","real","y"),
("dig-03-esme-data-information-sheet.docx","Ecosystem Service Map Explorer: Data Information Sheet for the Defra Data Services Platform",D,N,E+"2a5c1759-6d7e-4a23-8c6c-644fd184c2ef&fileName=READ ME_ESME data information sheet.docx",OGL+" (EA open data)","real","y"),
("dig-04-esme-data-export-schema.xlsx","ESME Data export schema V1.1 (field list)",D,N,E+"2a5c1759-6d7e-4a23-8c6c-644fd184c2ef&fileName=ESME Data export schema Final V1.1_DSP.xlsx",OGL+" (EA open data)","real","y"),
("dig-05-access-environmental-data.pptx","Access environmental data (Defra Data Services Platform) (slides)",D,"","https://www.gov.uk/guidance/download-environmental-data",OGL,"derived (python-pptx, verbatim page text)","y"),
("risk-01-ncerm-properties-at-risk.xlsx","National Coastal Erosion Risk Mapping 2024: properties at risk (April 2026)",R,"",E+"0a6f72dd-8a02-4b5a-8a98-2d65ef47b323&fileName=NCERM2024_PropertiesAtRisk_v202604.xlsx",OGL+" (EA open data)","real","y"),
("risk-02-flood-model-locations.docx","Flood Model Locations dataset description",R,D,E+"d1b22ba1-7d01-42db-a150-0bacdb8af93b&fileName=LIT 72976 - Flood Model Locations.docx",OGL+" (EA open data)","real","y"),
("risk-03-fcerm-strategy-annex-c.pdf","National FCERM Strategy for England: Annex C, benefits, costs and funding (2020)",R,F,A+"5f5f9671d3bf7f723e21c088/15482_Environment_agency_digital_AnnexC_PDFA.pdf",OGL,"real","y"),
("risk-04-surface-water-availability-charging.docx","Surface Water Availability for Water Resource Charging (product description 2022)",R,F,E+"c4ecb4e9-2182-4d38-9ef0-2e947d692947&fileName=Surface_Water_Availability_for_WR_Charging_product_description 2022.docx",OGL+" (EA open data)","real","y"),
]
assert all(os.path.exists("raw/"+r[0]) for r in rows), [r[0] for r in rows if not os.path.exists("raw/"+r[0])]
extra=set(os.listdir("raw"))-{r[0] for r in rows}; print("unlisted:",extra)
with open("gold.csv","w",newline="",encoding="utf-8") as f:
    w=csv.writer(f);w.writerow(["file","theme","secondary_theme"])
    for r in rows:w.writerow([r[0],r[2],r[3]])
with open("SOURCES.md","w",encoding="utf-8") as f:
    f.write("# DocMap test corpus: sources\n\nOne sector: the Environment Agency (England) and its parent Defra group. All files are Crown copyright, Open Government Licence v3.0 (OGL). EA datasets on environment.data.gov.uk carry a blank licence field in the data.gov.uk catalogue; EA publishes them as open data under OGL.\nDerived files are marked in the real/derived column.\n\n")
    f.write("| file | format | theme | title | source URL | licence | real/derived | text layer |\n|---|---|---|---|---|---|---|---|\n")
    for r in rows:
        f.write(f"| {r[0]} | {r[0].rsplit('.',1)[1]} | {r[2]} | {r[1]} | <{r[4].replace(' ','%20')}> | {r[5]} | {r[6]} | {r[7]} |\n")
from collections import Counter
print(Counter(r[0].rsplit('.',1)[1] for r in rows),Counter(r[2] for r in rows))

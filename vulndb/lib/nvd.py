import datetime
import gzip
import json
import logging
import tempfile

import requests

import vulndb.lib.config as config
import vulndb.lib.db as dbLib
from vulndb.lib import CvssV3, Vulnerability, VulnerabilitySource, VulnerabilityDetail

logging.basicConfig(
    level=logging.INFO, format="%(levelname)s [%(asctime)s] %(message)s"
)
LOG = logging.getLogger(__name__)

# Start year of historic cve data
start_year = config.nvd_start_year
# Current time
now = datetime.datetime.now()
# Size of the stream to read and write to the file
download_chunk_size = 128
# Create database
db = dbLib.get()


class NvdSource(VulnerabilitySource):
    """NVD CVE source. This uses CVE json 1.1 format that are split based on the year
    """

    def download_all(self):
        """Download all historic cve data
        """
        data_list = []
        for y in range(now.year, int(start_year) - 1, -1):
            data = self.fetch(y)
            self.store(data)
            data_list += data
        return data_list

    def download_recent(self):
        """Method which downloads the recent CVE gzip from NVD
        """
        data = self.fetch("recent")
        self.store(data)
        return data

    def fetch(self, year):
        """Private Method which downloads the given CVE gzip from NVD
        """
        url = config.nvd_url % dict(year=year)
        LOG.info("Download NVD CVE from {}".format(url))
        with tempfile.NamedTemporaryFile() as tf:
            r = requests.get(url, stream=True)
            for chunk in r.iter_content(chunk_size=download_chunk_size):
                tf.write(chunk)
            tf.flush()
            with gzip.open(tf.name, "rb") as gzipjf:
                cve_data = gzipjf.read()
                try:
                    json_data = json.loads(cve_data)
                    return self.convert(json_data)
                except Exception:
                    logging.warning("Exception while parsing NVD CVE feed")
                    return None

    def convert(self, cve_data):
        """Convert cve data to Vulnerability
        """
        items = cve_data.get("CVE_Items")
        data = []
        for cve_item in items:
            v = NvdSource.convert_vuln(cve_item)
            if v:
                data.append(v)
        return data

    def refresh(self):
        """Refresh CVE data"""
        return self.download_all()

    def store(self, data):
        """Store data in the database
        """
        docs = dbLib.store(db, data)
        return docs

    def bulk_search():
        """
        Bulk search the resource instead of downloading the information
        :return: Vulnerability result
        """
        raise NotImplementedError

    @staticmethod
    def convert_vuln(vuln):
        id = vuln["cve"]["CVE_data_meta"]["ID"]
        problem_type = ""

        if (
            vuln["cve"]["problemtype"]["problemtype_data"]
            and vuln["cve"]["problemtype"]["problemtype_data"][0]["description"]
        ):
            problem_type = vuln["cve"]["problemtype"]["problemtype_data"][0][
                "description"
            ][0]["value"]
        cvss_v3 = None
        severity = None
        base_score = None
        description = vuln["cve"]["description"]["description_data"][0]["value"]
        rdata = vuln["cve"]["references"]["reference_data"]
        related_urls = [r["url"] for r in rdata]
        if "baseMetricV3" in vuln["impact"]:
            cvss_data = vuln["impact"]["baseMetricV3"]["cvssV3"]
            cvss_data["exploitabilityScore"] = vuln["impact"]["baseMetricV3"][
                "exploitabilityScore"
            ]
            cvss_data["impactScore"] = vuln["impact"]["baseMetricV3"]["impactScore"]
            cvss_v3 = CvssV3(
                base_score=cvss_data["baseScore"],
                exploitability_score=cvss_data["exploitabilityScore"],
                impact_score=cvss_data["impactScore"],
                attack_vector=cvss_data["attackVector"],
                attack_complexity=cvss_data["attackComplexity"],
                privileges_required=cvss_data["privilegesRequired"],
                user_interaction=cvss_data["userInteraction"],
                scope=cvss_data["scope"],
                confidentiality_impact=cvss_data["confidentialityImpact"],
                integrity_impact=cvss_data["integrityImpact"],
                availability_impact=cvss_data["availabilityImpact"],
            )
            severity = cvss_data["baseSeverity"]
            base_score = cvss_v3.base_score
        details = NvdSource.convert_vuln_detail(vuln)
        if not details:
            return None
        return Vulnerability(
            id,
            problem_type,
            base_score,
            severity,
            description,
            related_urls,
            details,
            cvss_v3,
            vuln["lastModifiedDate"],
        )

    @staticmethod
    def convert_vuln_detail(vuln):
        nodes_list = vuln["configurations"]["nodes"]
        details = []
        for node in nodes_list:
            cpe_list = []
            # For AND operator we store all the cpe_matches thus
            # increasing the false-positives. But this is better than leaving
            # the CPE out altogether. Grafeas format unfortunately is not
            # suitable for AND/OR based vulnerability storage
            # min and max_affected_version can sometimes include the excluded version
            # thus, further increasing the false positives
            if node["operator"] == "AND":
                for cc in node.get("children", []):
                    cpe_list += cc["cpe_match"]
            cpe_list += node.get("cpe_match", [])
            for cpe in cpe_list:
                detail = {}
                if cpe["vulnerable"]:
                    detail["cpe_uri"] = cpe["cpe23Uri"]
                    detail["min_affected_version"] = cpe.get(
                        "versionStartIncluding", cpe.get("versionStartExcluding")
                    )
                    detail["max_affected_version"] = cpe.get(
                        "versionEndIncluding", cpe.get("versionEndExcluding")
                    )
                    detail["source_update_time"] = vuln["lastModifiedDate"]
                    details.append(VulnerabilityDetail.from_dict(detail))
        if not details:
            return None
        return details

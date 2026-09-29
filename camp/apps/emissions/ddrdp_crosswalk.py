"""
Hand-kept crosswalk from a normalised DDRDP project or dairy name
(ddrdp.normalise_name()) to the CADD dairy it names, for grants
import_ddrdp couldn't match by name and mailing city (or a unique name
Valley-wide). Extend it from import_ddrdp's "Unmatched" printout, one entry
at a time, each with a comment saying why: what CADD calls the dairy and
where, and what the PDF calls the project and where.
"""

CROSSWALK = {
    # '<normalised project or dairy name>': <cadd_id>,
    # CADD: "<CADD name>", <CADD mailing city>; PDF: "<PDF project title>", <PDF city>
}

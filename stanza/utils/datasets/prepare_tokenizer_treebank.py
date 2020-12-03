"""
Prepares train, dev, test for a treebank

For example, do
  python -m stanza.utils.datasets.prepare_tokenizer_treebank TREEBANK
such as
  python -m stanza.utils.datasets.prepare_tokenizer_treebank UD_English-EWT

and it will prepare each of train, dev, test

There are macros for preparing all of the UD treebanks at once:
  python -m stanza.utils.datasets.prepare_tokenizer_treebank ud_all
  python -m stanza.utils.datasets.prepare_tokenizer_treebank all_ud
Both are present because I kept forgetting which was the correct one

There are a few special case handlings of treebanks in this file:
  - UD_English-EWT has the MWTs stripped
  - all Vietnamese treebanks have special post-processing to handle
    some of the difficult spacing issues in Vietnamese text
  - treebanks with train and test but no dev split have the
    train data randomly split into two pieces
  - however, instead of splitting very tiny treebanks, we skip those
"""

import glob
import os
import random
import re
import shutil
import subprocess

import stanza.utils.datasets.common as common
import stanza.utils.datasets.postprocess_vietnamese_tokenizer_data as postprocess_vietnamese_tokenizer_data
import stanza.utils.datasets.prepare_tokenizer_data as prepare_tokenizer_data
import stanza.utils.datasets.preprocess_ssj_data as preprocess_ssj_data

from stanza.models.common.constant import treebank_to_short_name

CONLLU_TO_TXT_PERL = os.path.join(os.path.split(__file__)[0], "conllu_to_text.pl")

def read_sentences_from_conllu(filename):
    sents = []
    cache = []
    with open(filename) as infile:
        for line in infile:
            line = line.strip()
            if len(line) == 0:
                if len(cache) > 0:
                    sents += [cache]
                    cache = []
                continue
            cache += [line]
        if len(cache) > 0:
            sents += [cache]
    return sents

def write_sentences_to_conllu(filename, sents):
    with open(filename, 'w') as outfile:
        for lines in sents:
            for line in lines:
                print(line, file=outfile)
            print("", file=outfile)

def split_train_file(treebank, train_input_conllu,
                     train_output_conllu, train_output_txt,
                     dev_output_conllu, dev_output_txt):
    # set the seed for each data file so that the results are the same
    # regardless of how many treebanks are processed at once
    random.seed(1234)

    # read and shuffle conllu data
    sents = read_sentences_from_conllu(train_input_conllu)
    random.shuffle(sents)
    n_dev = int(len(sents) * XV_RATIO)
    assert n_dev >= 1, "Dev sentence number less than one."
    n_train = len(sents) - n_dev

    # split conllu data
    dev_sents = sents[:n_dev]
    train_sents = sents[n_dev:]
    print("Train/dev split not present.  Randomly splitting train file")
    print(f"{len(sents)} total sentences found: {n_train} in train, {n_dev} in dev.")

    # write conllu
    write_sentences_to_conllu(train_output_conllu, train_sents)
    write_sentences_to_conllu(dev_output_conllu, dev_sents)

    # use an external script to produce the txt files
    subprocess.check_output(f"perl {CONLLU_TO_TXT_PERL} {train_output_conllu} > {train_output_txt}", shell=True)
    subprocess.check_output(f"perl {CONLLU_TO_TXT_PERL} {dev_output_conllu} > {dev_output_txt}", shell=True)

    return True

def prepare_labels(input_txt_copy, input_conllu_copy, tokenizer_dir, short_name, short_language, dataset):
    prepare_tokenizer_data.main([input_txt_copy,
                                 input_conllu_copy,
                                 "-o", f"{tokenizer_dir}/{short_name}-ud-{dataset}.toklabels",
                                 "-m", f"{tokenizer_dir}/{short_name}-ud-{dataset}-mwt.json"])

    if short_language == "vi":
        postprocess_vietnamese_tokenizer_data.main([input_txt_copy,
                                                    "--char_level_pred", f"{tokenizer_dir}/{short_name}-ud-{dataset}.toklabels",
                                                    "-o", f"{tokenizer_dir}/{short_name}-ud-{dataset}.json"])

MWT_RE = re.compile("^[0-9]+[-][0-9]+")

def strip_mwt_from_conll(input_conllu, output_conllu):
    with open(input_conllu) as fin:
        with open(output_conllu, "w") as fout:
            for line in fin:
                if not MWT_RE.match(line):
                    fout.write(line)


def prepare_ud_dataset(treebank, udbase_dir, tokenizer_dir, short_name, short_language, dataset):
    os.makedirs(tokenizer_dir, exist_ok=True)

    input_txt = common.find_treebank_dataset_file(treebank, udbase_dir, dataset, "txt")
    input_txt_copy = f"{tokenizer_dir}/{short_name}.{dataset}.txt"

    input_conllu = common.find_treebank_dataset_file(treebank, udbase_dir, dataset, "conllu")
    input_conllu_copy = f"{tokenizer_dir}/{short_name}.{dataset}.gold.conllu"

    if short_name == "sl_ssj":
        preprocess_ssj_data.process(input_txt, input_conllu, input_txt_copy, input_conllu_copy)
    elif short_name == "en_ewt":
        # For a variety of reasons we want to strip the MWT from English
        # One reason in particular is that other English datasets do not
        # have MWT, so if we have the eventual goal of mixing datasets,
        # it will be impossible to do while keeping MWT.
        # Another reason is even if we kept MWT in EWT when mixing datasets,
        # it would be very difficult for users to switch between the two
        strip_mwt_from_conll(input_conllu, input_conllu_copy)
        shutil.copyfile(input_txt, input_txt_copy)
    else:
        shutil.copyfile(input_txt, input_txt_copy)
        shutil.copyfile(input_conllu, input_conllu_copy)

    prepare_labels(input_txt_copy, input_conllu_copy, tokenizer_dir, short_name, short_language, dataset)

def process_ud_treebank(treebank, udbase_dir, tokenizer_dir, short_name, short_language):
    """
    Process a normal UD treebank with train/dev/test splits

    SL-SSJ and Vietnamese both use this code path as well.
    """
    prepare_ud_dataset(treebank, udbase_dir, tokenizer_dir, short_name, short_language, "train")
    prepare_ud_dataset(treebank, udbase_dir, tokenizer_dir, short_name, short_language, "dev")
    prepare_ud_dataset(treebank, udbase_dir, tokenizer_dir, short_name, short_language, "test")


XV_RATIO = 0.2

def process_partial_ud_treebank(treebank, udbase_dir, tokenizer_dir, short_name, short_language):
    """
    Process a UD treebank with only train/test splits

    For example, in UD 2.7:
      UD_Buryat-BDT
      UD_Galician-TreeGal
      UD_Indonesian-CSUI
      UD_Kazakh-KTB
      UD_Kurmanji-MG
      UD_Latin-Perseus
      UD_Livvi-KKPP
      UD_North_Sami-Giella
      UD_Old_Russian-RNC
      UD_Sanskrit-Vedic
      UD_Slovenian-SST
      UD_Upper_Sorbian-UFAL
      UD_Welsh-CCG
    """
    train_input_conllu = common.find_treebank_dataset_file(treebank, udbase_dir, "train", "conllu")
    train_output_conllu = f"{tokenizer_dir}/{short_name}.train.gold.conllu"
    train_output_txt = f"{tokenizer_dir}/{short_name}.train.txt"
    dev_output_conllu = f"{tokenizer_dir}/{short_name}.dev.gold.conllu"
    dev_output_txt = f"{tokenizer_dir}/{short_name}.dev.txt"

    if not split_train_file(treebank=treebank,
                            train_input_conllu=train_input_conllu,
                            train_output_conllu=train_output_conllu,
                            train_output_txt=train_output_txt,
                            dev_output_conllu=dev_output_conllu,
                            dev_output_txt=dev_output_txt):
        return

    prepare_labels(train_output_txt, train_output_conllu, tokenizer_dir, short_name, short_language, "train")
    prepare_labels(dev_output_txt, dev_output_conllu, tokenizer_dir, short_name, short_language, "dev")

    # the test set is already fine
    prepare_ud_dataset(treebank, udbase_dir, tokenizer_dir, short_name, short_language, "test")


def process_treebank(treebank, paths):
    """
    Processes a single treebank into train, dev, test parts

    TODO
    Currently assumes it is always a UD treebank.  There are Thai
    treebanks which are not included in UD.

    Also, there is no specific mechanism for UD_Arabic-NYUAD or
    similar treebanks, which need integration with LDC datsets
    """
    udbase_dir = paths["UDBASE"]
    tokenizer_dir = paths["TOKENIZE_DATA_DIR"]

    train_txt_file = common.find_treebank_dataset_file(treebank, udbase_dir, "train", "txt")
    if not train_txt_file:
        raise ValueError("Cannot find train file for treebank %s" % treebank)

    short_name = treebank_to_short_name(treebank)
    short_language = short_name.split("_")[0]

    print("Preparing data for %s: %s, %s" % (treebank, short_name, short_language))

    if not common.find_treebank_dataset_file(treebank, udbase_dir, "dev", "txt"):
        process_partial_ud_treebank(treebank, udbase_dir, tokenizer_dir, short_name, short_language)
    else:
        process_ud_treebank(treebank, udbase_dir, tokenizer_dir, short_name, short_language)


def main():
    common.main(process_treebank)

if __name__ == '__main__':
    main()

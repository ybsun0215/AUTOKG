import itertools
import re
import openai
import os
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import ast
from collections import Counter
from tqdm import tqdm

class KGExploration:
    def __init__(self, **explorer_config) -> None:
        # API_base
        # self.API_Base = explorer_config["OpenAI_API_Base"]
        # API_key
        self.key_list = explorer_config["API_key_list"]
        # Model name
        self.model_name = "gpt-4o-2024-08-06"
        # seed_path
        self.seed_file_path = explorer_config["seed_file_path"]
        # prompt_path
        self.entity_extratction_prompt_path = explorer_config["ke_entity_extratction_prompt"]
        self.relation_extratction_prompt_path = explorer_config["ke_relation_extratction_prompt"]
        self.entity_labeling_prompt_path = explorer_config["ke_entity_labeling_prompt"]
        self.entity_type_fusion_prompt = explorer_config["ke_entity_type_fusion_prompt"]
        self.relation_type_fusion_prompt = explorer_config["ke_relation_type_fusion_prompt"]
        # save_path
        self.entity_file_path = explorer_config["save_ke_entity_path"]
        self.relation_file_path = explorer_config["save_ke_relation_path"]
        self.entity_label_path = explorer_config["save_ke_entity_label_path"]
        self.entity_type_path = explorer_config["save_ke_entity_type_path"]
        self.relation_type_batch_path = explorer_config["save_ke_relation_type_path"]

    def load_message(self, prompt_content):
        instruct_content = ""
        message = [{"role": "system", "content": instruct_content}]
        message.append({"role": "user", "content": prompt_content})
        return message

    def call_llm(self, llm_input, api_key):
        openai.api_key = api_key
        response = openai.ChatCompletion.create(
            model=self.model_name,
            messages=llm_input,
            temperature=0,
            max_tokens=4096
        )
        return response['choices'][0]['message']['content'].strip()

    def split_list(self, lst, chunk_size):
        return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

    def read_seed_files(self):
        # check seed_path
        if os.path.isdir(self.seed_file_path):
            files = os.listdir(self.seed_file_path)
            files_list = [os.path.join(self.seed_file_path, file) for file in files]
        else:
            files_list = []
            print("Invalid seed path")
        # read file_content
        file_content_list = []
        for path in files_list:
            try:
                with open(path, 'r', encoding='utf-8') as file:
                    reader = csv.reader(file)
                    result = list(reader)
                    for i in range(len(result)):
                        file_content_list.append(result[i][0])
            except Exception as e:
                print(e)
        return file_content_list

    def entity_extraction(self, chunk, prompt_content, api_key, index):
        prompt_content = prompt_content.replace("${text}$", chunk)
        llm_input = self.load_message(prompt_content)
        entity_result_form_1 = self.call_llm(llm_input, api_key)
        entity_result_form_2 = re.sub(r'\([^)]*\)', '()', entity_result_form_1)
        entity_result = re.sub(r'<[^>]*>', '<>', entity_result_form_2)
        try:
            entity_list = entity_result.split("\n")[1].split(", ")
            entities = ', '.join(entity_list)
        except:
            entities = ""
        return index, entities

    def process_entity_extraction(self, chunk_list):
        entity_list = [None] * len(chunk_list)
        entity_extraction_prompt_content = open(self.entity_extratction_prompt_path, 'r', encoding='utf-8').read()
        with ThreadPoolExecutor(max_workers=len(self.key_list)) as executor:
            futures = {
                executor.submit(self.entity_extraction, chunk, entity_extraction_prompt_content,
                                self.key_list[idx % len(self.key_list)], idx): idx for idx, chunk in enumerate(chunk_list)
            }
            for future in tqdm(as_completed(futures), desc= "Entity Extraction",total=len(futures)):
                index, entities = future.result()
                entity_list[index] = entities
        return chunk_list, entity_list

    def relation_extraction(self, chunk, prompt_content, entity_pairs, api_key, index):
        formatted_pairs = ast.literal_eval(entity_pairs)
        string_pairs = "; ".join(f"({item[0]}, {item[1]})" for item in formatted_pairs)
        prompt_content = prompt_content.replace("${text}$", chunk).replace('${entity_pairs}$', string_pairs)
        llm_input = self.load_message(prompt_content)
        relation_result = self.call_llm(llm_input, api_key)
        try:
            relation_triples = relation_result.split("\n")[1]
        except:
            relation_triples = ""
        return index, relation_triples

    def process_relation_extraction(self, chunk_list, entity_pair_list):
        relation_triple_list = [None] * len(chunk_list)
        relation_extraction_prompt_content = open(self.relation_extratction_prompt_path, 'r', encoding='utf-8').read()
        with ThreadPoolExecutor(max_workers=len(self.key_list)) as executor:
            futures = {
                executor.submit(
                    self.relation_extraction, chunk, relation_extraction_prompt_content, entity,
                    self.key_list[idx % len(self.key_list)], idx): idx for idx, (chunk, entity) in enumerate(zip(chunk_list, entity_pair_list))
            }
            for future in tqdm(as_completed(futures), desc= "Relation Extraction",total=len(futures)):
                index, relation_triples = future.result()
                relation_triple_list[index] = relation_triples
        return relation_triple_list

    def read_entity_infos(self):
        chunk_list= []
        entity_pair_list = []
        with open(self.entity_file_path, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            result = list(reader)
            for i in range(len(result)):
                chunk_list.append(result[i][0])
                entity_pair_list.append(result[i][2])
        return chunk_list, entity_pair_list

    def entity_type_labeling(self, chunk, prompt_content, entity, api_key, index):
        prompt_content = prompt_content.replace("${text}$", chunk).replace('${entities}$', entity)
        llm_input = self.load_message(prompt_content)
        entity_label_result = self.call_llm(llm_input, api_key)
        try:
            entity_types = entity_label_result.split("\n\n")[0].split("\n")[1]
        except:
            entity_types = ""
        return index, entity_types

    def process_entity_type_labeling(self, chunk_list, entity_list):
        entity_type_list = [None] * len(chunk_list)
        entity_type_label_prompt_content = open(self.entity_labeling_prompt_path, 'r', encoding='utf-8').read()
        with ThreadPoolExecutor(max_workers=len(self.key_list)) as executor:
            futures = {
                executor.submit(
                    self.entity_type_labeling, chunk, entity_type_label_prompt_content, entity,
                    self.key_list[idx % len(self.key_list)], idx): idx for idx, (chunk, entity) in enumerate(zip(chunk_list, entity_list))
            }
            for future in tqdm(as_completed(futures), desc= "Entity Type Labeling",total=len(futures)):
                index, entity_types = future.result()
                entity_type_list[index] = entity_types
        return entity_type_list

    def read_entity_types(self):
        entity_type_list = []
        with open(self.entity_label_path, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reader:
                if row[2]:
                    try:
                        parts = row[2].split('; ')
                        results = [part.split(': ')[1].strip().replace(';', '') for part in parts if ': ' in part]
                        entity_type_list.extend(results)
                    except (ValueError, SyntaxError) as e:
                        print(f"Error parsing row: {row[3]}. Error: {e}")
        counter = Counter(entity_type_list)
        unique_entity_type_list = sorted(counter.keys(), key=lambda x: counter[x], reverse=True)
        elements_to_remove = ['none', 'none;', 'none.']
        for element in elements_to_remove:
            if element in unique_entity_type_list:
                unique_entity_type_list.remove(element)
        seen = set()
        final_entity_type_list = []
        for item in unique_entity_type_list:
            if item.lower() not in seen:
                seen.add(item.lower())
                final_entity_type_list.append(item)
        return final_entity_type_list

    def entity_type_fusion(self, entity_type_def_list):
        print("************************* Entity Type Fusion *************************")
        prompt_content = open(self.entity_type_fusion_prompt,'r',encoding='utf-8').read().replace('${entity types}$', str(entity_type_def_list))
        llm_input = self.load_message(prompt_content)
        entity_fuse_result = self.call_llm(llm_input, self.key_list[0])
        try:
            entity_type_definitions = entity_fuse_result.split("\n\n")[0].split("\n")[1:]
            entity_types = entity_fuse_result.split("\n\n")[1].split("\n")[1:]
        except:
            entity_types = ""
            entity_type_definitions = ""
        return entity_type_definitions, entity_types

    def read_relation_types(self):
        relation_type_list = []
        with open(self.relation_file_path, mode='r', encoding='utf-8') as file:
            reader = csv.reader(file)
            for row in reader:
                if row[2]:
                    try:
                        triplets = row[2].split('; ')
                        second_elements = [triplet.strip('()').split(', ')[1] for triplet in triplets]
                        relation_type_list.extend(second_elements)
                    except:
                        pass
        counter = Counter(relation_type_list)
        unique_relation_type_list = sorted(counter.keys(), key=lambda x: counter[x], reverse=True)
        return unique_relation_type_list

    def relation_type_fusion(self, relation_type_def_list):
        print("************************* Relation Type Fusion *************************")
        prompt_content = open(self.relation_type_fusion_prompt,'r',encoding='utf-8').read().replace('${relation types}$', str(relation_type_def_list))
        llm_input = self.load_message(prompt_content)
        relation_fuse_result = self.call_llm(llm_input, self.key_list[0])
        try:
            relation_type_definitions = relation_fuse_result.split("\n\n")[0].split("\n")[1:]
            relation_types = relation_fuse_result.split("\n\n")[1].split("\n")[1:]
        except:
            relation_types = ""
            relation_type_definitions = ""
        return relation_type_definitions, relation_types

    def save_extracted_entities(self,chunk_list, entity_list):
        result = []
        for index in range(len(chunk_list)):
            pairs = list(itertools.combinations(entity_list[index].split(', '), 2))
            task = {
                "chunk": chunk_list[index],
                "entities": entity_list[index],
                "entity_pairs": pairs,
            }
            result.append(task)
        df = pd.DataFrame(result)
        df.to_csv(self.entity_file_path, index=False,header=False)

    def save_extracted_relations(self, chunk_list, entity_pair_list, relation_triple_list):
        result = []
        for index in range(len(chunk_list)):
            task = {
                "chunk": chunk_list[index],
                "entities": entity_pair_list[index],
                "relation_triples": relation_triple_list[index],
            }
            result.append(task)
        df = pd.DataFrame(result)
        df.to_csv(self.relation_file_path, index=False,header=False)

    def save_labeled_entity_types(self, chunk_list, entity_list, entity_type_list):
        result = []
        for index in range(len(chunk_list)):
            task = {
                "chunk": chunk_list[index],
                "entities": entity_list[index],
                "entity_types": entity_type_list[index],
            }
            result.append(task)
        df = pd.DataFrame(result)
        df.to_csv(self.entity_label_path, index=False,header=False)

    def save_fused_entity_types(self, entity_type_definitions, entity_types):
        result = []
        entity_def_dict = {}
        for item in entity_type_definitions:
            typename, definition = item.split(': ', 1)
            entity_def_dict[typename.strip()] = definition.strip()
        entity_type_dict = {}
        for item in entity_types:
            typename, subtypes = item.split(': ', 1)
            entity_type_dict[typename.strip()] = subtypes.replace(';', '').strip('[]')
        for typename, definition in entity_def_dict.items():
            subtypes = entity_type_dict.get(typename, '')
            if subtypes:
                subtypes_list = list(set(subtypes.split(', ')))
                if typename in subtypes_list:
                    subtypes_list.remove(typename)
                subtypes = ', '.join(subtypes_list)
            else:
                subtypes = ''
            result.append({
                "typename": typename,
                "definition": definition,
                "subtypes": subtypes
            })
        for typename, subtypes in entity_type_dict.items():
            if typename not in entity_def_dict:
                result.append({
                    "typename": typename,
                    "definition": '',
                    "subtypes": subtypes
                })
        df = pd.DataFrame(result)
        df.to_csv(self.entity_type_path, index=False, header=False)

    def save_fused_relation_types(self, relation_type_definitions, relation_types):
        definitions = dict(item.split(": ", 1) for item in relation_type_definitions)
        subtypes = {}
        for entry in relation_types:
            for pair in entry.split("; "):
                typename, subtype_str = pair.split(": ", 1)
                typename = typename.strip()
                subtype_str = subtype_str.strip()
                if subtype_str not in subtypes:
                    subtypes[subtype_str] = []
                subtypes[subtype_str].append(typename)
        result = []
        for typename, definition in definitions.items():
            unique_subtypes = list(set(subtypes.get(typename, [])))
            result.append({
                "typename": typename,
                "definition": definition,
                "subtypes": unique_subtypes
            })
        df = pd.DataFrame(result)
        df.to_csv(self.relation_type_batch_path, index=False, header=False)
#!/usr/bin/env python2.7
#coding=UTF-8
'''
Given two or more parallel outputs of make_json.py for the same sentences, 
merges them into a single annotation to the extent that they are compatible.
Output in the same JSON format as the input.

@author: Nathan Schneider (nschneid@cs.cmu.edu)
@since: 2013-02-20
'''
from __future__ import print_function, division
import os, re, sys, fileinput, json, math
from collections import Counter, defaultdict

from graph import FUDGGraph, simplify_coord, upward, downward
from spanningtrees import spanning
from measures import *

def mw2FEMW(ann, n):
	'''Given the JSON object for an annotation and the name of a MW node, convert it to an FEMW node'''
	assert n.startswith('MW(')
	assert n in ann['nodes'],(n,ann['nodes'])
	assert 'FE'+n not in ann['nodes']
	
	ann['nodes'][ann['nodes'].index(n)] = 'FE'+n
	ann['n2w']['FE'+n] = ann['n2w'][n]
	del ann['n2w'][n]
	
	# create single-word tokens
	for tkn in ann['n2w']['FE'+n]:
		if 'W('+tkn+')' not in ann['nodes']:	# may already be there due to an overlapping FEMW
			ann['nodes'].append('W('+tkn+')')
			ann['n2w']['W('+tkn+')'] = [tkn]
	
	# ensure edges use FEMW(...)
	for e in ann['node_edges']:
		x,y,lbl = e
		assert x!=y
		if x==n: e[0] = 'FE'+n
		if y==n: e[1] = 'FE'+n
		assert e[0]!=e[1]
	
	# derive "deps", "anaph", and "coords" from "node_edges"
	ann['anaph'] = [[x,y] for x,y,lbl in ann['node_edges'] if lbl=='Anaph']
	coordinators = {}
	conjuncts = {}
	for x,y,lbl in ann['node_edges']:
		if lbl=='Coord':
			coordinators.setdefault(x,set()).add(y)
		elif lbl=='Conj':
			conjuncts.setdefault(x,set()).add(y)
	assert set(coordinators.keys())==set(conjuncts.keys())
	ann['varnodes'] = list(conjuncts.keys())
	ann['coords'] = [[v,list(conjs),list(coordinators[v])] for v,conjs in conjuncts.items()]
	ann['deps'] = [[x,y,lbl] for x,y,lbl in ann['node_edges'] if lbl not in ('Anaph','Coord','Conj')]

def merge(annsJ, updatelex=False, escapebrackets=False):

	for j,annJ in enumerate(annsJ):
	
				
	
				#print(j,file=sys.stderr)
				lexnodes = {n for n in annJ['nodes'] if 'W(' in n}	# excluding root
				assert set(annJ['n2w'].keys())==lexnodes,('Mismatch between nodes and n2w in input',j,lexnodes^set(annJ['n2w'].keys()),annJ)
				
				# normalize tokens: bracket escaping
				if escapebrackets:
					ESCAPES = {'(': '_LRB_', ')': '_RRB_', '<': '_LAB_', '>': '_RAB_', '[': '_LSB_', ']': '_RSB_', '{': '_LCB_', '}': '_RCB_'}
					for i,tkn in enumerate(annJ['tokens']):
						if re.search('|'.join(re.escape(k) for k in ESCAPES.keys()), tkn):
							assert updatelex
							for k,v in ESCAPES.items():
								annJ['tokens'][i] = annJ['tokens'][i].replace(k,v)
				
				if j==0:
					mergedJ = json.loads(json.dumps(annJ))	# hacky deepcopy
					continue
				
				# normalize tokens: indexing
				# some tokens may not be tilde-indexed in all annotations
				# note that if a token is repeated, it cannot have been used in the graph; 
				# so there is no need to update nodes/edges when adding tilde indices
				assert len(annJ['tokens'])==len(mergedJ['tokens'])
				if annJ['tokens']!=mergedJ['tokens']:
					missing = set(enumerate(mergedJ['tokens']))-set(enumerate(annJ['tokens']))
					repeated = {(i,wtype) for i,wtype in missing if mergedJ['tokens'].count(wtype)>1}
					for i,wtype in repeated:
						assert annJ['tokens'][i][:annJ['tokens'][i].rindex('~')]==wtype
						assert annJ['tokens'][i] not in mergedJ['tokens']
						mergedJ['tokens'][i] = annJ['tokens'][i]
						if updatelex:
							for ann in annsJ[:-1]:
								ann['tokens'][i] = mergedJ['tokens'][i]
					
					extra = set(enumerate(annJ['tokens']))-set(enumerate(mergedJ['tokens']))
					repeated = {(i,wtype) for i,wtype in extra if annJ['tokens'].count(wtype)>1}
					for i,wtype in repeated:
						assert updatelex,wtype	# may be triggered by ambiguous token that is sometimes (but not always) indexed
						assert mergedJ['tokens'][i][:mergedJ['tokens'][i].rindex('~')]==wtype
						assert mergedJ['tokens'][i] not in annJ['tokens']
						annJ['tokens'][i] = mergedJ['tokens'][i]
						
					#print('After attempting to reconcile tilde indices:',annJ['tokens'],mergedJ['tokens'],file=sys.stderr)
					
					assert annJ['tokens']==mergedJ['tokens'],('Differences in token disambiguation not automatically reconciled--please update manually:',set(enumerate(annJ['tokens']))^set(enumerate(mergedJ['tokens'])))
				
				
				# TODO: smart renaming of conflicting FEs?
				conflictingN2W = {k for k in (set(annJ['n2w'].keys()) & set(mergedJ['n2w'].keys())) if annJ['n2w'][k]!=mergedJ['n2w'][k]}
				assert not conflictingN2W,('Differences in lexical node-word mappings not automatically reconciled--please update manually:',conflictingN2W)
				
				# TODO: smart renaming of conflicting variables?
				'''
				conflictingVN2W = {k for k in (set(annJ['extra_node2words'].keys()) & set(mergedJ['extra_node2words'].keys())) if annJ['extra_node2words'][k]!=mergedJ['extra_node2words'][k]}
				for k in conflictingVN2W:
					annJ['extra_node2words'][k+'_'] = annJ['extra_node2words'][k]	# TODO: Hacky
					del annJ['extra_node2words'][k]
					annJ['nodes'][annJ['nodes'].index(k)] = k+'_'
					for e in annJ['node_edges']:
						x,y,lbl = e
						if x==k: e[0] = k+'_'
						if y==k: e[1] = k+'_'
				print(annJ)
				'''
				annVN2W = {varname: [conjuncts,coordinators] for varname,conjuncts,coordinators in annJ['coords']}
				mergedVN2W = {varname: [conjuncts,coordinators] for varname,conjuncts,coordinators in mergedJ['coords']}
				conflictingVN2W = {varname for varname in (set(annVN2W.keys()) & set(mergedVN2W.keys())) if set(annVN2W[varname][1])!=set(mergedVN2W[varname][1])}
				assert not conflictingVN2W,('Differences in coordination variable not automatically reconciled--please update manually:',conflictingVN2W)


				# union the ordinary edges
				for e in annJ['node_edges']:
					if e not in mergedJ['node_edges']:
						mergedJ['node_edges'].append(list(e))
				
				# special nodes
				for varname in set(annVN2W.keys()) - set(mergedVN2W.keys()):
					mergedJ['varnodes'].append(varname)
					mergedJ['coords'].append(json.loads(json.dumps([varname]+annVN2W[varname])))


				# register any new nodes
				# if there are any multiwords not in all annotations, include them in the merge with the FEMW prefix
				# include in the merge the union of all single-word nodes not represented by an FEMW

				for q in range(2 if updatelex else 1):	# repeat in case an FEMW is introduced in the first iteration, necessitating new W nodes

					# newly encountered lexical nodes
					for n in set(annJ['nodes']) - set(mergedJ['nodes']):
						if n=='**':
							continue
						if n.startswith('MW('):	# this annotation has MW, the merge doesn't, so make it an FEMW
							if 'FE'+n not in mergedJ['nodes']:	# merge doesn't have an FEMW, so make one
								if n in mergedJ['nodes']:	# merge has MW
									assert False,'I think this is outdated code, should never be reached'
									mw2FEMW(mergedJ, n)
									if updatelex:
										for ann in annsJ[:-1]:
											if n in ann['nodes']:
												mw2FEMW(ann, n)
								else:	# merge had/has single-words only (or perhaps, overlapping (FE)MWs?)	# TODO: overlap case? FEMW that is the union of overlapping MWs?
										# single-words would have been removed at the beginning of the loop
										# slightly hacky: add MW, then convert it to FEMW (this also converts the edges)
									for ann in [mergedJ]+(annsJ[:-1] if updatelex else []):
										ann['nodes'].append(n)
										ann['n2w'][n] = list(annJ['n2w'][n])
										mw2FEMW(ann, n)

							if updatelex:
									mw2FEMW(annJ, n)
						elif n.startswith('FEMW(') and n[3:] in mergedJ['nodes']:
							# this annotation has FEMW, merge has MW
							for ann in [mergedJ]+(annsJ[:-1] if updatelex else []):
								mw2FEMW(ann, n[3:])
						else:
							assert n.startswith('FE') or n.startswith('W(') or n.startswith('$'),n
						
							considerupdating = [mergedJ] + (annsJ[:-1] if updatelex and n.startswith('W(') else [])
							for ann in considerupdating:
								if n in ann['nodes']: continue
								if n.startswith('W('):	# ensure single word is not already covered by a MW (FEMW is OK)
									if any(lexnode.startswith('MW(') and n[2:-1] in tkns for lexnode,tkns in ann['n2w'].items()):
										continue
								elif n.startswith('FEMW('):	# do not add an FEMW if it overlaps with an MW
									femwtkns = annJ['n2w'][n]
									if any(lexnode.startswith('MW(') and set(femwtkns)&set(mwtkns) for lexnode,mwtkns in ann['n2w'].items()):
										continue
								ann['nodes'].append(n)
								if n in annJ['n2w']:
									ann['n2w'][n] = list(annJ['n2w'][n])
							'''
							if n.startswith('W('):	# ensure single word is not already covered by a MW (FEMW is OK)
								tkn = n[2:-1]
								if any(lexnode.startswith('MW(') and tkn in tkns for lexnode,tkns in mergedJ['node2words'].items()):
									continue
							#assert n!='W($$)'
							mergedJ['nodes'].append(n)
							if n in annJ['node2words']:
								mergedJ['node2words'][n] = list(annJ['node2words'][n])
							if n.startswith('W(') and updatelex:
								for ann in annsJ[:-1]:
									ann['nodes'].append(n)
									ann['node2words'][n] = list(annJ['node2words'][n])
							'''
				
					# lexical items in the merge of previous annotations, but not this one
					# note that the merge can acquire single-word nodes not in either annotation 
					# if a MW from one of the annotations is converted to an FEMW in the merge!
					for n in set(mergedJ['nodes']) - set(annJ['nodes']):
						if n=='**':
							continue
						elif n.startswith('MW('):
							# in the merge, relax MW to an FEMW
							mw2FEMW(mergedJ, n)
							newfemmw = True
							if updatelex:
								for ann in annsJ[:-1]:
									if n in ann['nodes']:
										mw2FEMW(ann, n)
						else:
							assert n.startswith('FE') or n.startswith('W(') or n.startswith('$'),n
						
							considerupdating = [annJ] if updatelex and n.startswith('W(') else []
							for ann in considerupdating:
								if n in ann['nodes']: continue
								if n.startswith('W('):	# ensure single word is not already covered by a MW (FEMW is OK)
									if any(lexnode.startswith('MW(') and n[2:-1] in mwtkns for lexnode,mwtkns in ann['n2w'].items()):
										continue
								elif n.startswith('FEMW('):	# do not add an FEMW if it overlaps with an MW
									femwtkns = mergedJ['n2w'][n]
									if any(lexnode.startswith('MW(') and set(femwtkns)&set(mwtkns) for lexnode,mwtkns in ann['n2w'].items()):
										continue
								ann['nodes'].append(n)
								if n in mergedJ['n2w']:
									ann['n2w'][n] = list(mergedJ['n2w'][n])
									
				
	
				if updatelex:
					yy = {k for k in mergedJ['n2w'] if k not in annJ['n2w'] and not k.startswith('FEMW(')}
					assert not yy,(yy,mergedJ['nodes'],mergedJ['n2w'],annJ['nodes'],annJ['n2w'])
					xx = {k for k in annJ['n2w'] if k not in mergedJ['n2w']}
				else:
					xx = {k for k in annJ['n2w'] if k not in mergedJ['n2w'] and (not k.startswith('MW(') or 'FE'+k not in mergedJ['n2w'])}
				assert not xx,xx

					
				# a token may be used by multiple FEMWs, but for any other type of lexical node it must appear only once
				tokenreps = Counter([t for tkns in mergedJ['n2w'].values() for t in tkns])
				tokennodetypes = defaultdict(set)
				for n,tkns in mergedJ['n2w'].items():
					for t in tkns:
						tokennodetypes[t].add(n[:n.index('(')])
				for tkn,reps in tokenreps.items():
					if reps>1:
						assert 'MW' not in tokennodetypes[tkn],('Token used in multiple lexical expressions, at least one of which is a MW',tkn,tokennodetypes)

	assert len(set(mergedJ['nodes']))==len(mergedJ['nodes']),('Nodes are not unique in merge: '+' '.join(n for n in mergedJ['nodes'] if mergedJ['nodes'].count(n)>1))
	for i in range(len(annsJ)):
		assert len(set(annsJ[i]['nodes']))==len(annsJ[i]['nodes']),('Nodes are not unique in annsJ['+str(i)+']: '+' '.join(n for n in annsJ[i]['nodes'] if annsJ[i]['nodes'].count(n)>1))

	lexnodes = {n for n in mergedJ['nodes'] if 'W(' in n}	# excluding root
	assert set(mergedJ['n2w'].keys())==lexnodes,('Mismatch between nodes and n2w in merge',j,lexnodes^set(mergedJ['n2w'].keys()),mergedJ)
	
	# ensure single-word elements of FEMWs also have their own entries
	for ann in [mergedJ]+(annsJ if updatelex else []):
		for n,tkns in ann['n2w'].items():
			if n.startswith('FEMW('):
				for tkn in tkns:
					assert 'W('+tkn+')' in ann['n2w'],(tkn,ann['n2w'])
	
	# sort nodes by token order
	mergedJ['nodes'].sort(key=lambda n: ((['**']+mergedJ['tokens']).index(mergedJ['n2w'][n][0]) if n in mergedJ['n2w'] else float('inf'),
										 n.split('(')[0]))
	
	return mergedJ


def main(annsFF, verbose=False, simplifycoords=False, updatelex=False, escapebrackets=False):
	assert len(annsFF)>=2
	
	i = 0
	allC = Counter()
	while True:	# iterate over items
		annsJ = []	# JSON input objects, one per annotator
		anns = []	# FUDG graphs, one per annotator
		locs = []
		
		try:
			for j,annsF in enumerate(annsFF):	# iterate over annotators
				#print('.',j,file=sys.stderr)
				ln = next(annsF)
				loc, sent, annJS = ln[:-1].split('\t')
				locs.append(loc)
				if j==0:
					sent0 = sent
				
				try:
					assert sent==sent0,(sent0,sent)	# TODO: hmm, why is this failing?
				except AssertionError as ex:
					print(ex, file=sys.stderr)

				
				annJ = json.loads(annJS)
				annsJ.append(annJ)
				if verbose:
					print(i, loc, '<<', sent, file=sys.stderr)
					print(annJ, file=sys.stderr)
				#a = FUDGGraph(annJ)
				#anns.append(a)
				
				if simplifycoords:
					aX = FUDGGraph(annJ)
					simplify_coord(aX)
					annsJ[-1] = annJ = aX.to_json_simplecoord()
					#if verbose: print(annJ, file=sys.stderr)
				
			mergedJ = merge(annsJ, updatelex=updatelex)
				
			output = '|'.join(locs) + '\t' + sent + '\t' + json.dumps(mergedJ)
		
			if verbose:
				print(output, file=sys.stderr)
				
			try:
				a = FUDGGraph(mergedJ)
				print(output)
				try:
					c = single_ann_measures(a)
					if verbose: print(c, file=sys.stderr)
					allC += c
				except Exception as ex:
					print('CANNOT EVALUATE MERGE',loc,'::',ex, file=sys.stderr)
					allC['invalid'] += 1
				
			except Exception as ex:
				if 'cycle' in ex.message:
					print('CANNOT MERGE',loc,'::',ex, file=sys.stderr)
				else:
					raise
				print()	# blank line--invalid merge!
			
			
			i += 1
			
		except StopIteration:
			break

	print(allC, file=sys.stderr)

if __name__=='__main__':
	annsFF = []
	args = sys.argv[1:]
	opts = {'updatelex': True}
	
	while args and args[0].startswith('-'):
		opts[{'-v': 'verbose', '-s': 'singleonly', '-c': 'simplifycoords', '-b': 'escapebrackets', 
			'-l': 'strict_lexical_node_agreement'}[args.pop(0)]] = True
	
	if 'strict_lexical_node_agreement' in opts:
		opts['updatelex'] = False
		del opts['strict_lexical_node_agreement']
	
	assert len(args)>=2
	
	while args:
		annsF = fileinput.input([args.pop(0)])
		annsFF.append(annsF)
	
	main(annsFF,**opts)

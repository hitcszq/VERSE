import sys
import fileinput
import argparse
import time
import itertools
import pickle
import random
import codecs
from collections import defaultdict
from sklearn import svm
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.feature_extraction import DictVectorizer
from scipy.sparse import coo_matrix, hstack, vstack
import numpy as np

from ClassifierStuff import *
from SentenceModel import *

def findEventTrigger(sentenceData,triggerid):
	for sentenceid, sentence in enumerate(sentenceData):
		if triggerid in sentence.predictedEntityLocs:
			return sentenceid,sentence.predictedEntityLocs[triggerid]
	raise RuntimeError('Unable to find location of event trigger ID ('+str(triggerid)+') in sentences')
	
def findArgumentTrigger(sentenceData,triggerid):
	for sentenceid, sentence in enumerate(sentenceData):
		if triggerid in sentence.knownEntityLocs:
			return sentenceid,sentence.knownEntityLocs[triggerid]
	raise RuntimeError('Unable to find location of argument trigger ID ('+str(triggerid)+') in sentences')

def findTrigger(sentenceData,triggerid):
	for sentenceid, sentence in enumerate(sentenceData):
		if triggerid in sentence.predictedEntityLocs:
			return sentenceid,sentence.predictedEntityLocs[triggerid]
		if triggerid in sentence.knownEntityLocs:
			return sentenceid,sentence.knownEntityLocs[triggerid]
	raise RuntimeError('Unable to find location of trigger ID ('+str(triggerid)+') in sentences')

	
def generateRelationExamples(sentenceAndEventData,targetRelations,targetArguments,sentenceRange,doFiltering):
	examples = []
	classes = []
	relTypes = []
	
	for filename in sentenceAndEventData:
		#print filename
		(sentenceData,relations,modifiers) = sentenceAndEventData[filename]
		
		positiveRelations = {}
		positiveRelationsProcessed = []
		for (relName,id1,id2) in relations:
			sentenceid1,locs1 = findTrigger(sentenceData,id1)
			sentenceid2,locs2 = findTrigger(sentenceData,id2)

			type1 = sentenceData[sentenceid1].locsToTriggerTypes[tuple(locs1)]
			type2 = sentenceData[sentenceid2].locsToTriggerTypes[tuple(locs2)]
			#if sentenceid1 != sentenceid2:
			#	print "WARNING: Relation split across sentences (%s and %s)" % (id1,id2)
			#	continue
			#sentenceid = sentenceid1

			#print "POSITIVE", relName, type1, type2

			#key = (relName,type1,type2)
			#key = relName

			#print relName
			if not relName in targetRelations:
				continue

			key = (sentenceid1,tuple(locs1),sentenceid2,tuple(locs2))
			classid = targetRelations[relName]
			positiveRelations[key] = classid
			#positiveRelations[key] = True

				
		# Now we go through all sentences and create examples for all possible token combinations
		# Then check if any are already marked as positive and add to the appropriate list of examples
		for sentenceid1 in range(len(sentenceData)):
			for sentenceid2 in range(max(sentenceid1-sentenceRange,0),min(sentenceid1+sentenceRange+1,len(sentenceData))):
				#print sentenceid1,sentenceid2
				sentence1,sentence2 = sentenceData[sentenceid1],sentenceData[sentenceid2]
			
				eventLocsAndTypes1 = [ (sentence1.predictedEntityLocs[id],sentence1.predictedEntityTypes[id]) for id in sentence1.predictedEntityTypes ]
				argsLocsAndTypes1 = [ (sentence1.knownEntityLocs[id],sentence1.knownEntityTypes[id]) for id in sentence1.knownEntityTypes ]
				possibleLocsAndTypes1 = eventLocsAndTypes1 + argsLocsAndTypes1
				
				eventLocsAndTypes2 = [ (sentence2.predictedEntityLocs[id],sentence2.predictedEntityTypes[id]) for id in sentence2.predictedEntityTypes ]
				argsLocsAndTypes2 = [ (sentence2.knownEntityLocs[id],sentence2.knownEntityTypes[id]) for id in sentence2.knownEntityTypes ]
				possibleLocsAndTypes2 = eventLocsAndTypes2 + argsLocsAndTypes2
							
				for (locs1,type1),(locs2,type2) in itertools.product(possibleLocsAndTypes1,possibleLocsAndTypes2):
					if sentenceid1 == sentenceid2 and locs1 == locs2:
						continue

					key = (type1,type2)
					if doFiltering and not key in targetArguments:
						continue

					#print "POTENTIAL", type1, type2

					key = (sentenceid1,tuple(locs1),sentenceid2,tuple(locs2))
					example = Example(filename, sentenceData, arg1_sentenceid=sentenceid1, arg1_locs=locs1, arg2_sentenceid=sentenceid2, arg2_locs=locs2)
					examples.append(example)

					thisClass = 0
					if key in positiveRelations:
						thisClass = positiveRelations[key]
						#thisClass = 1
						positiveRelationsProcessed.append(key)
					classes.append(thisClass)
					relTypes.append((type1,type2))
						
		#print filename
		for key in positiveRelations:
			#assert key in allArgTriggerLocsProcessed, 'Unprocessed event trigger found: ' + str(key)
			if not key in positiveRelationsProcessed:
				print 'WARNING: Unprocessed argument trigger found: %s in file: %s' % (str(key), filename) 
			
	#for c,e in zip(classes,examples):
	#	print c,e

	#sys.exit(0)
				
	return classes, examples, relTypes

def createRelationClassifier(sentenceAndEventData,targetRelations,targetArguments,parameters=None,generateClassifier=True,sentenceRange=0,doFiltering=False):
	classes,examples,relTypes = generateRelationExamples(sentenceAndEventData,targetRelations,targetArguments,sentenceRange,doFiltering)
	assert min(classes) == 0, "Expecting negative cases in relation examples"
	assert max(classes) > 0, "Expecting positive cases in relation examples"
	#return buildClassifier(classes,examples,parameters)
	vectors,vectorizer,featureSelector = buildVectorizer(classes,examples,parameters)

	classifier = None
	if generateClassifier:
		classifier = buildClassifierFromVectors(classes,vectors,parameters)

	data = (classes,examples,vectors,relTypes)
	return data,vectorizer,featureSelector,classifier
	
def saveCOOMatrixToFile(matrix,filename):
	with open(filename,'w') as f:
		f.write("%%sparse\t%d\t%d\n" % (matrix.shape[0],matrix.shape[1]))
		for row,col,data in zip(matrix.row,matrix.col,matrix.data):
			line = "%d\t%d\t%f" % (row,col,data)
			f.write(line + "\n")

def loadCOOMatrixFromFile(filename):
	rows,cols = -1,-1
	data = []
	matrix = None
	with open(filename,'r') as f:
		header = True
		for line in f:
			if header:
				_,r,c = line.split("\t")
				rows,cols = int(r),int(c)
				header = False
			else:
				x,y,value = line.split("\t")
				x,y,value = int(x),int(y),float(value)
				data.append((x,y,value))

	xs = [ x for x,y,value in data ]
	ys = [ y for x,y,value in data ]
	vals = [ value for x,y,value in data ]

	matrix = coo_matrix((vals,(xs,ys)),shape=(rows,cols))
	return matrix

def loadNumpyArrayFromFile(filename):
	return np.loadtxt(filename,comments='%')

def loadMatrixFromFile(filename):
	with open(filename,'r') as f:
		header = f.readline().strip().split("\t")
	type,dim1,dim2 = header
	#dim1,dim2 = int(dim1),int(dim2)
	print filename, type
	if type == "%sparse":
		return loadCOOMatrixFromFile(filename)
	elif type == "%dense":
		return loadNumpyArrayFromFile(filename)
	else:
		raise RuntimeError("Unknown type of matrix: %s" % type)
# It's the main bit. Yay!
if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='VERSE Relation Extraction tool')

	parser.add_argument('--trainingFile', required=True, type=str, help='Parsed-text file containing the training data')
	parser.add_argument('--testingFile', required=True, type=str, help='Parsed-text file containing the test data to predict modifications for')
	parser.add_argument('--relationDescriptions', required=True, type=str, help='Description file containing list of relation types with arguments to predict')
	parser.add_argument('--parameters', type=str, help='Parameters to use for feature construction, selection and classification')
	parser.add_argument('--outFile', type=str, help='Output filename for data with predicted modifications')
	args = parser.parse_args()

	parameters = {}
	if args.parameters:
		for arg in args.parameters.split(';'):
			name,value = arg.strip().split(":")
			parameters[name.strip()] = value.strip()
			
	sentenceRange = 0
	if "sentenceRange" in parameters:
		sentenceRange = int(parameters["sentenceRange"])
	
	trainFilename = args.trainingFile
	with open(trainFilename, 'r') as f:
		trainingSentenceAndEventData = pickle.load(f)
	print "Loaded " + trainFilename

	tmpTargetRelations = set()
	for filename,data in trainingSentenceAndEventData.iteritems():
		sentenceData = data[0]
		relations = data[1]

		for (relName,id1,id2) in relations:
			sentenceid1,locs1 = findTrigger(sentenceData,id1)
			sentenceid2,locs2 = findTrigger(sentenceData,id2)
			type1 = sentenceData[sentenceid1].locsToTriggerTypes[tuple(locs1)]
			type2 = sentenceData[sentenceid2].locsToTriggerTypes[tuple(locs2)]
			tmpTargetRelations.add((relName,type1,type2))

	#print tmpTargetRelations

	print "#"*30
	for relName,type1,type2 in tmpTargetRelations:
		print "%s\t%s\t%s" % (relName,type1,type2)
	print "#"*30

	doFiltering = False
	if 'doFiltering' in parameters and parameters['doFiltering'] == 'True':
		doFiltering = True

	#targetRelations = []
	targetRelations,targetArguments = set(),set()
	#typeLookup = {}
	with open(args.relationDescriptions,'r') as f:
		for line in f:
			nameAndArgs,type1,type2 = line.strip().split('\t')

			# Pull out the name of arguments and sort by the argument names
			nameAndArgsSplit = nameAndArgs.split(';')

			# Basically don't do anything if we aren't given the argument names
			if len(nameAndArgsSplit) == 1:
				targetRelations.add(tuple(nameAndArgsSplit))
				targetArguments.add((type1,type2))
			else: # Or do sort by argument names (if they are provided)
				relName,argName1,argName2 = nameAndArgs.split(';')
				relArgs = [(argName1,type1),(argName2,type2)]
				relArgs = sorted(relArgs)
				
				targetRelations.add((relName,relArgs[0][0],relArgs[1][0]))
				targetArguments.add((relArgs[0][1],relArgs[1][1]))

	targetRelations = list(targetRelations)
	targetRelations = sorted(targetRelations)

	targetRelationsToIDs = { arg:i+1 for i,arg in enumerate(targetRelations) }

	#print tionsToIDstargetEventsToIDs
	#print targetRelationsToIDs
	print "-"*30
	for targetRelation in targetRelations:
		print targetRelation
	print "-"*30
	for targetArgument in targetArguments:
		print targetArgument
	print "-"*30
	
	relData,argVec,argFS,argClf = createRelationClassifier(trainingSentenceAndEventData,targetRelationsToIDs,targetArguments,parameters,True,sentenceRange,doFiltering)

	with open(args.testingFile, 'r') as f:
		testingSentenceAndEventData = pickle.load(f)
	print "Loaded " + args.testingFile

	# Empty the test data of any existing predictions (in case we load the wrong test file)
	for filename in testingSentenceAndEventData:
		(sentenceData,relations,modifiers) = testingSentenceAndEventData[filename]
		# Empty relations
		relations = []
		
		testingSentenceAndEventData[filename] = (sentenceData,relations,modifiers)
		
	print "generate Argument Examples..."
	_,aExamples,aTypes = generateRelationExamples(testingSentenceAndEventData,targetRelationsToIDs,targetArguments,sentenceRange,doFiltering)
	
	print "vectorize, trim and predict..."

	aVectors = argVec.vectorize(aExamples)
	if not argFS is None:
		aVectors = argFS.transform(aVectors)
	aVectors = coo_matrix(aVectors)

	aPredictions = argClf.predict(aVectors)
	aProbs = argClf.predict_proba(aVectors)
	probColumns = { c:i for i,c in enumerate(argClf.classes_) }

	#predictedEventID = 1
	predictedTriggerID = 1000
	
	predictedEventIDPerFile = Counter()
	
	for i,(p,example) in enumerate(zip(aPredictions,aExamples)):
		if p != 0:
			relType = targetRelations[p-1]
			
			#eventType = thisRelation[1]
			#argTypes = thisRelation[2:]
			#assert len(argTypes) == 2, "Only processing binary relations for triggerless events"

			#eventType = thisRelation[0]
			
			sentenceFilename = example.filename
			sentenceID1,arg1Locs = example.arguments[0]
			sentenceID2,arg2Locs = example.arguments[1]


			sentence1 = testingSentenceAndEventData[sentenceFilename][0][sentenceID1]
			sentence2 = testingSentenceAndEventData[sentenceFilename][0][sentenceID2]

			sentence1.invertTriggers()
			sentence2.invertTriggers()

			arg1ID = sentence1.locsToTriggerIDs[tuple(arg1Locs)]
			arg2ID = sentence2.locsToTriggerIDs[tuple(arg2Locs)]

			type1ID = sentence1.locsToTriggerTypes[tuple(arg1Locs)]
			type2ID = sentence2.locsToTriggerTypes[tuple(arg2Locs)]

			#relType = typeLookup[type1ID]

			relations = testingSentenceAndEventData[sentenceFilename][1]
			
			prob = aProbs[i,probColumns[p]]

			newR = (relType,arg1ID,arg2ID,prob)
			#print "ADDING", newR
			relations.append(newR)
			#print "TEST",sentenceFilename,sentenceID1,sentenceID2,arg1Locs,arg2Locs,relType


	with open(args.outFile, 'w') as f:
		pickle.dump(testingSentenceAndEventData,f)
				
	print "Complete."

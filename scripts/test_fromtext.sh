#!/bin/bash
# Test script for litdb fromtext command

echo "Testing litdb fromtext command..."
echo ""

# Test 1: Reference with DOI
echo "Test 1: Reference with DOI"
litdb fromtext "A study by Kitchin, Examples of Effective Data Sharing in Scientific Publishing, ACS Catalysis, 2015, DOI: 10.1021/acscatal.5b00538" --model "ollama/llama3.3"

echo ""
echo "Test completed!"

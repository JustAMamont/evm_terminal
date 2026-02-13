// SPDX-License-Identifier: MIT
pragma solidity 0.8.33;

interface IUniswapV2Factory {
    function getPair(address tokenA, address tokenB) external view returns (address pair);
}
interface IUniswapV2Pair {
    function swap(uint amount0Out, uint amount1Out, address to, bytes calldata data) external;
    function getReserves() external view returns (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast);
}
interface IERC20 {
    function balanceOf(address owner) external view returns (uint);
    function approve(address spender, uint value) external returns (bool);
    function transfer(address to, uint value) external returns (bool);
    function transferFrom(address from, address to, uint value) external returns (bool);
}
interface IWETH {
    function deposit() external payable;
    function withdraw(uint) external;
}
interface ISwapRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 deadline;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }
    function exactInputSingle(ExactInputSingleParams calldata params) external payable returns (uint256 amountOut);
}
library UniswapV2Library {
    function sortTokens(address tokenA, address tokenB) internal pure returns (address token0, address token1) {
        require(tokenA != tokenB, 'IDENTICAL_ADDRESSES');
        (token0, token1) = tokenA < tokenB ? (tokenA, tokenB) : (tokenB, tokenA);
        require(token0 != address(0), 'ZERO_ADDRESS');
    }
    function pairFor(address factory, address tokenA, address tokenB) internal view returns (address pair) {
        (address token0, address token1) = sortTokens(tokenA, tokenB);
        pair = IUniswapV2Factory(factory).getPair(token0, token1);
    }
    function getReserves(address factory, address tokenA, address tokenB) internal view returns (uint reserveA, uint reserveB) {
        (address token0,) = sortTokens(tokenA, tokenB);
        (uint reserve0, uint reserve1,) = IUniswapV2Pair(pairFor(factory, tokenA, tokenB)).getReserves();
        (reserveA, reserveB) = tokenA == token0 ? (reserve0, reserve1) : (reserve1, reserve0);
    }
    function getAmountOut(uint amountIn, uint reserveIn, uint reserveOut) internal pure returns (uint amountOut) {
        require(amountIn > 0, 'INSUFFICIENT_INPUT_AMOUNT');
        require(reserveIn > 0 && reserveOut > 0, 'INSUFFICIENT_LIQUIDITY');
        uint amountInWithFee = amountIn * 9975;
        uint numerator = amountInWithFee * reserveOut;
        uint denominator = (reserveIn * 10000) + amountInWithFee;
        amountOut = numerator / denominator;
    }
}

contract TaxRouter {
    address public immutable factory;
    address public immutable WETH;
    address public immutable v3Router;
    address public feeReceiver;
    address public owner;
    uint public constant FEE_BASIS_POINTS = 10;
    uint public constant FEE_DENOMINATOR = 10000;
    mapping(address => bool) public isQuoteToken;
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event FeeReceiverChanged(address indexed newReceiver);
    error DeadlineExpired(uint256 deadline, uint256 timestamp);
    error InsufficientOutputAmount(uint256 amountRequired, uint256 amountReceived);
    error NotOwner(address caller);
    error ZeroAddress();
    error InvalidPath();
    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner(msg.sender);
        _;
    }
    constructor(address _factory, address _WETH, address _feeReceiver, address _v3Router) {
        factory = _factory;
        WETH = _WETH;
        feeReceiver = _feeReceiver;
        v3Router = _v3Router;
        owner = msg.sender;
        isQuoteToken[_WETH] = true;
    }
    receive() external payable {}

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }
    function setFeeReceiver(address _newReceiver) external onlyOwner {
        if (_newReceiver == address(0)) revert ZeroAddress();
        feeReceiver = _newReceiver;
        emit FeeReceiverChanged(_newReceiver);
    }
    function setQuoteToken(address token, bool status) external onlyOwner { isQuoteToken[token] = status; }
    function rescueTokens(address token, uint amount) external onlyOwner {
        if (token == address(0)) {
             (bool success,) = msg.sender.call{value: address(this).balance}("");
             require(success, "ETH Transfer Failed");
        } else {
             IERC20(token).transfer(msg.sender, amount);
        }
    }

    // --- V3 SWAP (STRICT ERC20) ---

    function swapV3Single(
        address tokenIn, address tokenOut, uint24 poolFee, uint256 amountIn,
        uint256 amountOutMin, address recipient, uint256 deadline
    ) external returns (uint256 amountOut) {
        if (deadline < block.timestamp) revert DeadlineExpired(deadline, block.timestamp);
        uint balBefore = IERC20(tokenIn).balanceOf(address(this));
        IERC20(tokenIn).transferFrom(msg.sender, address(this), amountIn);
        uint amountToSwap = IERC20(tokenIn).balanceOf(address(this)) - balBefore;
        bool isInputQuote = isQuoteToken[tokenIn];
        bool isOutputQuote = isQuoteToken[tokenOut];
        if (isInputQuote) {
            uint fee = (amountToSwap * FEE_BASIS_POINTS) / FEE_DENOMINATOR;
            amountToSwap -= fee;
            if (fee > 0) IERC20(tokenIn).transfer(feeReceiver, fee);
        }

        IERC20(tokenIn).approve(v3Router, 0);
        IERC20(tokenIn).approve(v3Router, amountToSwap);

        address recipientLoc = isOutputQuote ? address(this) : recipient;
        ISwapRouter.ExactInputSingleParams memory params = ISwapRouter.ExactInputSingleParams({
            tokenIn: tokenIn, tokenOut: tokenOut, fee: poolFee, recipient: recipientLoc, deadline: deadline,
            amountIn: amountToSwap, amountOutMinimum: 0, sqrtPriceLimitX96: 0
        });
        amountOut = ISwapRouter(v3Router).exactInputSingle(params);
        if (isOutputQuote) {
            uint fee = (amountOut * FEE_BASIS_POINTS) / FEE_DENOMINATOR;
            uint amountUser = amountOut - fee;
            if (amountUser < amountOutMin) revert InsufficientOutputAmount(amountOutMin, amountUser);
            if (fee > 0) IERC20(tokenOut).transfer(feeReceiver, fee);
            IERC20(tokenOut).transfer(recipient, amountUser);
            amountOut = amountUser;
        } else {
            if (amountOut < amountOutMin) revert InsufficientOutputAmount(amountOutMin, amountOut);
        }
    }

    // --- V2 SWAP (STRICT ERC20 & Tax Supported) ---

    function _swapSupportingFeeOnTransferTokens(address[] memory path, address _to) internal {
        for (uint i; i < path.length - 1; i++) {
            (address input, address output) = (path[i], path[i + 1]);
            (address token0,) = UniswapV2Library.sortTokens(input, output);
            IUniswapV2Pair pair = IUniswapV2Pair(UniswapV2Library.pairFor(factory, input, output));
            uint amountInput;
            uint amountOutput;
            {
                (uint reserve0, uint reserve1,) = pair.getReserves();
                (uint reserveInput, uint reserveOutput) = input == token0 ? (reserve0, reserve1) : (reserve1, reserve0);
                amountInput = IERC20(input).balanceOf(address(pair)) - reserveInput;
                amountOutput = UniswapV2Library.getAmountOut(amountInput, reserveInput, reserveOutput);
            }
            (uint amount0Out, uint amount1Out) = input == token0 ? (uint(0), amountOutput) : (amountOutput, uint(0));
            address to = i < path.length - 2 ? UniswapV2Library.pairFor(factory, output, path[i + 2]) : _to;
            pair.swap(amount0Out, amount1Out, to, new bytes(0));
        }
    }

    function swapExactTokensForTokens(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline) external returns (uint[] memory amounts) {
        if (deadline < block.timestamp) revert DeadlineExpired(deadline, block.timestamp);
        bool isInputQuote = isQuoteToken[path[0]];
        bool isOutputQuote = isQuoteToken[path[path.length - 1]];
        uint balBefore = IERC20(path[0]).balanceOf(address(this));
        IERC20(path[0]).transferFrom(msg.sender, address(this), amountIn);
        uint received = IERC20(path[0]).balanceOf(address(this)) - balBefore;
        if (isInputQuote) {
            uint fee = (received * FEE_BASIS_POINTS) / FEE_DENOMINATOR;
            received -= fee;
            if (fee > 0) IERC20(path[0]).transfer(feeReceiver, fee);
        }
        IERC20(path[0]).transfer(UniswapV2Library.pairFor(factory, path[0], path[1]), received);
        if (isOutputQuote) {
            _swapSupportingFeeOnTransferTokens(path, address(this));
            uint amtOut = IERC20(path[path.length-1]).balanceOf(address(this));
            uint fee = (amtOut * FEE_BASIS_POINTS) / FEE_DENOMINATOR;
            uint amountUser = amtOut - fee;
            if (amountUser < amountOutMin) revert InsufficientOutputAmount(amountOutMin, amountUser);
            if (fee > 0) IERC20(path[path.length-1]).transfer(feeReceiver, fee);
            IERC20(path[path.length-1]).transfer(to, amountUser);
            amounts = new uint[](path.length);
            amounts[path.length-1] = amountUser;
        } else {
            _swapSupportingFeeOnTransferTokens(path, to);
            amounts = new uint[](path.length);
        }
    }

    // --- Utility functions (e.g., for Auto-Fuel) ---
    // These functions handle native BNB but are NOT used for main trading swaps.

    function swapExactTokensForETH(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline) external {
        require(path[path.length - 1] == WETH, 'Invalid Path');
        if (deadline < block.timestamp) revert DeadlineExpired(deadline, block.timestamp);
        uint balBefore = IERC20(path[0]).balanceOf(address(this));
        IERC20(path[0]).transferFrom(msg.sender, address(this), amountIn);
        uint received = IERC20(path[0]).balanceOf(address(this)) - balBefore;
        IERC20(path[0]).transfer(UniswapV2Library.pairFor(factory, path[0], path[1]), received);
        _swapSupportingFeeOnTransferTokens(path, address(this));
        uint amountOut = IERC20(WETH).balanceOf(address(this));
        uint fee = (amountOut * FEE_BASIS_POINTS) / FEE_DENOMINATOR;
        uint amountUser = amountOut - fee;
        if (amountUser < amountOutMin) revert InsufficientOutputAmount(amountOutMin, amountUser);
        if (fee > 0) IERC20(WETH).transfer(feeReceiver, fee);
        IWETH(WETH).withdraw(amountUser);
        (bool success,) = to.call{value: amountUser}(new bytes(0));
        require(success, 'ETH Transfer Failed');
    }

    function swapExactETHForTokens(uint amountOutMin, address[] calldata path, address to, uint deadline) external payable {
        require(path[0] == WETH, 'Invalid Path');
        if (deadline < block.timestamp) revert DeadlineExpired(deadline, block.timestamp);
        
        uint amountIn = msg.value;
        IWETH(WETH).deposit{value: amountIn}();
        
        // This function is for utilities like auto-fuel, so fee logic is simple.
        uint fee = (amountIn * FEE_BASIS_POINTS) / FEE_DENOMINATOR;
        uint amountAfterFee = amountIn - fee;
        if (fee > 0) IERC20(WETH).transfer(feeReceiver, fee);
        
        IERC20(WETH).transfer(UniswapV2Library.pairFor(factory, path[0], path[1]), amountAfterFee);
        
        uint balanceBefore = IERC20(path[path.length - 1]).balanceOf(to);
        _swapSupportingFeeOnTransferTokens(path, to);
        uint balanceAfter = IERC20(path[path.length - 1]).balanceOf(to);
        
        if (balanceAfter - balanceBefore < amountOutMin) {
            revert InsufficientOutputAmount(amountOutMin, balanceAfter - balanceBefore);
        }
    }
}